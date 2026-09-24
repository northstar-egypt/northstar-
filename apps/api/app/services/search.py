"""Scout search: structured filters, plus an honest account of the query text.

The natural language half of this screen needs sentence-transformer embeddings and the
embedding model choice is still open (`docs/wireframes/README.md`). `apps/web/lib/api.ts`
says the filter half should ship first, so that is what this is.

The query box still does something, and what it does is deliberately modest. A handful of
patterns map cleanly onto columns: an age or an age range, a height, a position, a tier, a
sport, "egypt eligible". Those become filters. Anything left over is treated as part of a
player's name. Terms naming a scouting concept the platform cannot answer yet, such as xG or
preferred foot, are recognised and do nothing.

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

from app.models.enums import FootballTier, Sport
from app.models.measurement import Measurement
from app.models.player import Player
from app.schemas.views import SearchRequest
from app.services import cohort

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

_STOPWORDS = {
    "a", "an", "and", "the", "with", "who", "that", "for", "of", "in", "at",
    "players", "player", "show", "me", "find", "years", "year", "old", "yo",
}

# Terms a scout will reasonably type that this search cannot serve. They get a chip marked
# `understood: false` and change nothing, which is the case the frontend fixture illustrates
# with "left footed: no data". Listing them explicitly is better than letting them fall
# through to the name matcher and silently return zero players.
_NO_DATA_TERMS = {
    "xg": "expected goals",
    "goals": "goals per 90",
    "assists": "assists per 90",
    "percentile": "percentile filters",
    "footed": "preferred foot",
    "lefty": "preferred foot",
    "righty": "preferred foot",
    "potential": "potential rating",
    "breakout": "breakout flag",
    "similar": "similarity search",
    "fast": "speed relative to peers",
    "quick": "speed relative to peers",
    "tall": "height relative to peers",
    "strong": "strength",
}


def parse_query(text: str) -> tuple[dict, list[dict], list[str]]:
    """Pull what can be understood out of a query string.

    Returns (filters, chips, name_terms). Every token ends up in exactly one chip, so the
    chips account for everything the scout typed. The screen renders them under the heading
    "How this was read", and `understood: false` is styled as a warning.

    The contract that heading implies, and which this function keeps: **a chip marked
    `understood: false` changed nothing about the results.** Anything that did affect the
    search is marked true and says how, in the `key: value` style the frontend fixture uses.

    That rules out the tempting shortcut of treating every unrecognised word as a name filter
    while greying it out. "under 17 striker fast ahmed" would then return nothing, because no
    Egyptian player is named "fast", while the screen claimed the word was ignored. Words that
    name a concept this search cannot serve are listed in `_NO_DATA_TERMS` and genuinely do
    nothing; the rest are treated as name fragments and say so.
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

    for token in re.findall(r"[A-Za-z]+", remaining):
        lowered = token.lower()
        if lowered in _STOPWORDS:
            continue
        if lowered in _POSITIONS:
            filters["position"] = _POSITIONS[lowered]
            chips.append({"label": f"position: {_POSITIONS[lowered]}", "understood": True})
        elif lowered in {tier.value for tier in FootballTier}:
            filters["tier"] = lowered
            chips.append({"label": f"tier: {lowered}", "understood": True})
        elif lowered in {"football", "footballer"}:
            filters["sport"] = Sport.FOOTBALL.value
            chips.append({"label": "sport: football", "understood": True})
        elif lowered in {"tabletennis", "pingpong"}:
            filters["sport"] = Sport.TABLE_TENNIS.value
            chips.append({"label": "sport: table tennis", "understood": True})
        elif lowered in _NO_DATA_TERMS:
            # Recognised as a real scouting concept, and nothing here can answer it. The chip
            # says so and the search is unaffected.
            chips.append(
                {"label": f"{_NO_DATA_TERMS[lowered]}: no data", "understood": False}
            )
        else:
            # Treated as part of a name. It does change the results, so the chip is marked
            # understood and states the interpretation rather than implying it was ignored.
            name_terms.append(token)
            chips.append({"label": f"name: {token}", "understood": True})

    return filters, chips, name_terms


def apply_filters(
    stmt: Select,
    request: SearchRequest,
    extra: dict,
    today: date,
    name_terms: list[str] | None = None,
) -> Select:
    """Turn the request plus anything parsed out of the query into SQL predicates."""
    merged = {
        "sport": request.sport or extra.get("sport"),
        "tier": request.tier or extra.get("tier"),
        "position": request.position or extra.get("position"),
        "sex": request.sex,
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
        stmt = stmt.where(Player.tier == merged["tier"])
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

    if name_terms:
        # Plain case-insensitive contains, one clause per word, all of which must match, so
        # "ahmed hassan" does not return every Ahmed. This is not the natural language search
        # the screen is eventually for and it is not pretending to be.
        for word in name_terms:
            pattern = f"%{word}%"
            stmt = stmt.where(
                or_(Player.full_name.ilike(pattern), Player.known_as.ilike(pattern))
            )

    return stmt


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
