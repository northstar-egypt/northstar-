"""Scout search: structured filters, plus an honest account of the query text.

The query box reads a scout's sentence in three layers:

1. Patterns that map cleanly onto columns: an age or an age range, a height, a position or a
   playing style, a tier, a sport, a gender, "egypt eligible". Those become filters. The
   sport and gender are read in English and Arabic ("table tennis", "ping pong", "تنس طاولة",
   "girls", "بنات"), and playing styles come from the sport modules.
2. The rest is split into phrases (at commas, "and", "but", "with"...), and each phrase is
   read by app/concepts.py as one of a fixed list of things the platform computes ("small
   for his age" is the bottom quarter of height for age), or as an ask it has no data for
   ("left footed"). Keywords first, then a local embedding model for phrases keywords miss.
3. A phrase that is neither is a name, matched in Arabic or Latin script and any common
   spelling (app/names.py).

Every term comes back as a chip, and the screen prints them under "How this was read". The
rule those chips have to keep is simple and is the whole reason this file is careful:

    a chip marked `understood: false` changed nothing about the results

A search box that silently ignores half of what was typed is worse than one that cannot parse
at all, because the scout believes the results answered their question. A search box that
greys a word out *and then filters on it anyway* is worse still, because it returns an empty
list while claiming the word was ignored. Both are avoided here.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app import concepts, names, sports
from app.models.enums import FootballTier, Sport
from app.models.measurement import Measurement
from app.models.player import Player
from app.schemas.views import SearchRequest
from app.services import cohort, concept_filter

# Positions the generator produces. Kept here rather than in a database lookup because the
# position value set is an open question in docs/schema.md and hard-coding it in one place is
# easier to undo than hard-coding it in three.
_POSITIONS = {
    "gk": "GK", "goalkeeper": "GK", "keeper": "GK",
    "cb": "CB", "lb": "LB", "rb": "RB", "defender": "CB", "fullback": "LB",
    "cdm": "CDM", "cm": "CM", "cam": "CAM", "midfielder": "CM",
    "lw": "LW", "rw": "RW", "winger": "LW",
    "st": "ST", "striker": "ST", "forward": "ST",
}

# The sport and the gender, as a scout would type them. Matched on the whole text before it
# is split into words, because "table tennis" read word by word is two name terms, and so is
# "تنس طاولة". Arabic has no \b, so its words are bounded by whitespace.
_SPORT_WORDS = (
    (
        Sport.TABLE_TENNIS.value,
        "table tennis",
        re.compile(
            r"\btable[- ]?tennis\b|\bping[- ]?pong\b"
            r"|(?<!\S)تنس\s+(?:ال)?طاولة(?!\S)|(?<!\S)بينج\s*بونج(?!\S)",
            re.IGNORECASE,
        ),
    ),
    (
        Sport.FOOTBALL.value,
        "football",
        re.compile(
            r"\bfootball(?:ers?)?\b|\bsoccer\b|(?<!\S)كر[ةه]\s+(?:ال)?قدم(?!\S)|(?<!\S)كور[ةه](?!\S)",
            re.IGNORECASE,
        ),
    ),
)
_GENDER_WORDS = (
    ("female", "girls", re.compile(r"\b(?:girls?|women|female)\b|(?<!\S)بنات(?!\S)", re.I)),
    ("male", "boys", re.compile(r"\b(?:boys?|men|male)\b|(?<!\S)[اأ]?ولاد(?!\S)", re.I)),
)

_STOPWORDS = {
    "a", "an", "and", "the", "with", "who", "that", "for", "of", "in", "at",
    "players", "player", "show", "me", "find", "years", "year", "old", "yo",
}

# Where one phrase ends and the next begins: punctuation, and joining words standing alone.
_PHRASE_BREAK = re.compile(
    r"[,;.!?،]|\b(?:and|but|with|who|also|plus)\b|(?<!\S)(?:و|لكن|بس|وكمان)(?!\S)",
    re.IGNORECASE,
)


def _role_words() -> list[tuple[str, str, re.Pattern]]:
    """(sport, role, pattern) for every role in the sport modules other than football's.

    Football positions are codes ("CAM") with synonyms scouts use ("winger"), in
    `_POSITIONS`. Other sports' roles are words already ("chopper", "all_round"), so they are
    read from the module: a new sport's playing styles become searchable with no change here.
    "all_round" matches "all round", "all-round" and "allround", and a plural "s".
    """
    out = []
    for module in sports.registry().values():
        if module.sport == Sport.FOOTBALL.value:
            continue
        for role in module.roles:
            body = r"[- _]?".join(re.escape(part) for part in role.split("_"))
            out.append((module.sport, role, re.compile(rf"\b{body}s?\b", re.IGNORECASE)))
    return out


def _sport_label(sport: str) -> str:
    return sport.replace("_", " ")


def parse_query(
    text: str, *, can_use_flags: bool = True, reader: concepts.Reader | None = None
) -> tuple[dict, list[dict], list[str]]:
    """Pull what can be understood out of a query string.

    Returns (filters, chips, name_terms). Every word ends up in a chip, so the chips account
    for everything the scout typed. The screen renders them under the heading "How this was
    read", and `understood: false` is styled as a warning.

    The contract that heading implies, and which this function keeps: **a chip marked
    `understood: false` changed nothing about the results.** Anything that did affect the
    search is marked true and says how.

    `filters["concepts"]` lists the concepts to filter on (app/concepts.py). A caller who may
    not see flags (a player's own account) cannot filter on one: the chip says so and the
    search is unaffected. `reader` is the embedding model; None reads with keywords alone.
    """
    filters: dict = {}
    chips: list[dict] = []
    name_terms: list[str] = []
    if not text.strip():
        return filters, chips, name_terms

    remaining = text.strip()

    # "under 17", "u17", "under-16"
    match = re.search(r"\b(?:under[- ]?|u)(\d{1,2})\b", remaining, re.IGNORECASE)
    if match:
        filters["max_age"] = float(match.group(1))
        chips.append({"label": f"age: under {match.group(1)}", "understood": True})
        remaining = remaining[: match.start()] + " " + remaining[match.end() :]

    # "aged 14 to 16", "14-16"
    match = re.search(r"\b(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\b", remaining)
    if match:
        low, high = sorted((float(match.group(1)), float(match.group(2))))
        filters["min_age"], filters["max_age"] = low, high
        chips.append({"label": f"age: {int(low)} to {int(high)}", "understood": True})
        remaining = remaining[: match.start()] + " " + remaining[match.end() :]

    # "over 180cm", "taller than 175"
    match = re.search(
        r"\b(?:over|above|taller than)\s*(\d{2,3})\s*(?:cm)?\b", remaining, re.IGNORECASE
    )
    if match:
        filters["min_height_cm"] = float(match.group(1))
        chips.append({"label": f"height: over {match.group(1)}cm", "understood": True})
        remaining = remaining[: match.start()] + " " + remaining[match.end() :]

    if re.search(r"\begypt[- ]?eligible\b", remaining, re.IGNORECASE):
        filters["egypt_eligible_only"] = True
        chips.append({"label": "eligibility: Egypt", "understood": True})
        remaining = re.sub(r"\begypt[- ]?eligible\b", " ", remaining, flags=re.IGNORECASE)

    for sport, label, pattern in _SPORT_WORDS:
        if pattern.search(remaining):
            filters["sport"] = sport
            chips.append({"label": f"sport: {label}", "understood": True})
            remaining = pattern.sub(" ", remaining)

    genders = [(value, label) for value, label, pattern in _GENDER_WORDS if pattern.search(remaining)]
    for _, _, pattern in _GENDER_WORDS:
        remaining = pattern.sub(" ", remaining)
    if len(genders) == 1:
        filters["sex"] = genders[0][0]
        chips.append({"label": f"gender: {genders[0][1]}", "understood": True})
    elif genders:
        # "boys and girls" asks for both, which is no filter at all.
        chips.append({"label": "gender: boys and girls, both kept", "understood": False})

    # A playing style. One that only one sport has ("chopper") also says which sport. One that
    # is also a football word ("defender") means the football position unless the scout named
    # the other sport, which keeps every football search reading as it did before.
    for sport, role, pattern in _role_words():
        if not pattern.search(remaining):
            continue
        if filters.get("sport", sport) != sport:
            continue
        if role in _POSITIONS and "sport" not in filters:
            continue
        filters["position"] = role
        chips.append({"label": f"playing style: {role.replace('_', ' ')}", "understood": True})
        if "sport" not in filters:
            filters["sport"] = sport
            chips.append(
                {"label": f"sport: {_sport_label(sport)} (from the playing style)", "understood": True}
            )
        remaining = pattern.sub(" ", remaining)

    wanted: list[str] = []
    for phrase in _PHRASE_BREAK.split(remaining):
        words: list[str] = []
        for token in concepts.WORD.findall(phrase):
            lowered = token.lower()
            if lowered in _STOPWORDS:
                continue
            if lowered in _POSITIONS:
                filters["position"] = _POSITIONS[lowered]
                chips.append({"label": f"position: {_POSITIONS[lowered]}", "understood": True})
            elif lowered in {tier.value for tier in FootballTier}:
                filters["tier"] = lowered
                chips.append({"label": f"tier: {lowered}", "understood": True})
            else:
                words.append(token)
        if not words:
            continue

        reading = concepts.read(words, reader)
        for concept, how, source in reading.concepts:
            label = concept.label if how == "keyword" else f'{concept.label} (read from "{source}")'
            if not concept.answerable:
                # Recognised as a real scouting ask, and nothing here can answer it.
                chips.append({"label": label, "understood": False})
            elif concept.kind == "flag" and not can_use_flags:
                chips.append({"label": f"{label}: not available to your account", "understood": False})
            else:
                wanted.append(concept.id)
                chips.append({"label": label, "understood": True})
        for word in reading.unused:
            # Part of a phrase already read as a concept; it did not narrow anything.
            chips.append({"label": f"{word}: not used", "understood": False})
        for word in reading.leftover:
            # Treated as part of a name, in either script and any common spelling
            # (app/names.py). It does change the results, so the chip says how.
            name_terms.append(word)
            chips.append({"label": f"name: {word}", "understood": True})

    if wanted:
        filters["concepts"] = list(dict.fromkeys(wanted))
    return filters, chips, name_terms


def apply_filters(
    stmt: Select,
    request: SearchRequest,
    extra: dict,
    today: date,
    name_terms: list[str] | None = None,
    db: Session | None = None,
) -> Select:
    """Turn the request plus anything parsed out of the query into SQL predicates. Name terms
    and concepts need `db`: they are matched in Python (`_name_match_ids`,
    services/concept_filter.py)."""
    merged = {
        "sport": request.sport or extra.get("sport"),
        "tier": request.tier or extra.get("tier"),
        "position": request.position or extra.get("position"),
        "sex": request.sex or extra.get("sex"),
        "min_age": request.min_age if request.min_age is not None else extra.get("min_age"),
        "max_age": request.max_age if request.max_age is not None else extra.get("max_age"),
        "min_height_cm": (
            request.min_height_cm
            if request.min_height_cm is not None
            else extra.get("min_height_cm")
        ),
        "max_height_cm": request.max_height_cm,
        "egypt_eligible_only": request.egypt_eligible_only
        or extra.get("egypt_eligible_only", False),
    }

    if merged["sport"]:
        stmt = stmt.where(Player.primary_sport == merged["sport"])
    if merged["tier"]:
        # Pro, youth and diaspora are football tiers. A sport whose module has no tiers is not
        # filtered by one: the search screen starts on "youth", and applying it to table tennis
        # hid every table tennis player, even from a scout who typed "table tennis".
        tierless = [m.sport for m in sports.registry().values() if not m.uses_tier]
        stmt = stmt.where(or_(Player.tier == merged["tier"], Player.primary_sport.in_(tierless)))
    if merged["position"]:
        stmt = stmt.where(Player.position == merged["position"])
    if merged["sex"]:
        stmt = stmt.where(Player.sex == merged["sex"])
    if merged["egypt_eligible_only"]:
        stmt = stmt.where(Player.is_egypt_eligible.is_(True))
    if not request.include_minors:
        stmt = stmt.where(Player.is_minor.is_(False))
    if request.organization_id:
        from app.models.player_organization import PlayerOrganization

        stmt = stmt.where(
            Player.id.in_(
                select(PlayerOrganization.player_id)
                .where(PlayerOrganization.organization_id == request.organization_id)
                .where(PlayerOrganization.end_date.is_(None))
            )
        )

    # Age filters become date-of-birth bounds, which is the same question asked in a way an
    # index can answer.
    if merged["min_age"] is not None:
        stmt = stmt.where(
            Player.date_of_birth
            <= today - timedelta(days=int(merged["min_age"] * cohort.DAYS_PER_YEAR))
        )
    if merged["max_age"] is not None:
        stmt = stmt.where(
            Player.date_of_birth
            >= today - timedelta(days=int((merged["max_age"] + 1) * cohort.DAYS_PER_YEAR))
        )

    if merged["min_height_cm"] is not None or merged["max_height_cm"] is not None:
        stmt = stmt.where(Player.id.in_(_height_filter_ids(merged)))

    if name_terms or extra.get("concepts"):
        if db is None:
            raise ValueError("names and concepts are matched in Python and need a session")
    if name_terms:
        stmt = stmt.where(Player.id.in_(_name_match_ids(db, stmt, name_terms)))
    if extra.get("concepts"):
        by_id = {c.id: c for c in concepts.all_concepts()}
        wanted = [by_id[cid] for cid in extra["concepts"] if cid in by_id]
        stmt = stmt.where(
            Player.id.in_(concept_filter.matching_ids(db, stmt, wanted, today))
        )

    return stmt


def _name_match_ids(db: Session, stmt: Select, name_terms: list[str]) -> list:
    """Ids of the players left by every other filter whose name matches every name term.

    Matching runs in Python (app/names.py) because it reads Arabic and Latin spellings as
    sounds, which SQL cannot do. It reads the names of the players the other filters left,
    which is a few hundred here. A national database would want a precomputed, indexed key
    column instead; that is a schema change, so it waits until the size calls for it.
    """
    query = " ".join(name_terms)
    rows = db.execute(
        stmt.with_only_columns(Player.id, Player.full_name, Player.known_as).order_by(None)
    ).all()
    return [pid for pid, full_name, known_as in rows if names.matches(query, full_name, known_as)]


def _height_filter_ids(merged: dict):
    """Player ids whose most recent height falls inside the requested band."""
    latest = (
        select(
            Measurement.player_id.label("player_id"),
            func.max(Measurement.measured_at).label("measured_at"),
        )
        .where(Measurement.metric == "height_cm")
        .group_by(Measurement.player_id)
        .subquery()
    )
    stmt = (
        select(Measurement.player_id)
        .join(
            latest,
            and_(
                Measurement.player_id == latest.c.player_id,
                Measurement.measured_at == latest.c.measured_at,
            ),
        )
        .where(Measurement.metric == "height_cm")
    )
    if merged.get("min_height_cm") is not None:
        stmt = stmt.where(Measurement.value >= merged["min_height_cm"])
    if merged.get("max_height_cm") is not None:
        stmt = stmt.where(Measurement.value <= merged["max_height_cm"])
    return stmt


def highlights(player: Player, height_cm: float | None, age: float | None) -> list[str]:
    """Short phrases explaining why this player is in the results.

    Not a relevance score dressed up as prose. Each one restates a fact already on the card,
    which is all a filter-based search can honestly claim.
    """
    out: list[str] = []
    if player.tier:
        out.append(f"{player.tier} tier")
    if player.position:
        out.append(player.position)
    if height_cm is not None and age is not None and age < 18:
        out.append(f"{height_cm:.0f}cm at {age:.0f}")
    if player.is_egypt_eligible and player.tier == "diaspora":
        out.append("Egypt eligible, playing abroad")
    return out[:3]
