"""Squad Lab: pick a formation and players, see how well neighbours fit.

What the numbers are
--------------------
This is a rule of thumb, not a trained model, and nothing here is graded in ml/README.md. All
of it is configured in the sport module (`squadLab` in packages/shared/sports/football.json),
so the rules can be read and argued with in one place.

- **A trait** is one number from a player's own record, such as tackles per 90 or pass
  completion. The same trait is read from whatever the player's data has: an academy player's
  matches (`football.match.v1`) or a league player's latest season (`football.season_aggregate.v2`).
- **A trait is ranked, never compared raw.** It becomes a percentile among players of the same
  family (academy, or league and abroad) who play the position of the slot, so a centre back
  played up front is ranked on finishing against strikers. An academy player's 80 means the top
  fifth of academy players, not of the league. A percentile from fewer than `minPool` players
  is left out.
- **A link** between two neighbouring slots takes the traits that partnership needs (a winger's
  crossing, a striker's finishing in the air) and averages their percentiles. A side with no
  usable trait makes the link unknown, drawn grey, rather than guessed.
- **The team** has a score per line (the average of its players' slot scores), a chemistry
  score (the average known link) and balance, which is the weakest line.

What it cannot see
------------------
Goalkeepers are not scored: there is no goalkeeping data. Academy records hold no crosses,
dribbles, interceptions, clearances or duels, so an academy defender is judged on tackles and
passing alone. The response says how many numbers each score rests on.

Who is in it
------------
Only players with analytics consent in effect have traits or make up a ranking pool, as with
similar players (services/similar.py). A slot shows a player only if the caller may see them
(`access.may_view`). Coaches pick from their own organization and save squads for it; scouts
and federation staff pick from everyone they may see and can try line-ups without saving.
"""

from __future__ import annotations

import bisect
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from statistics import fmean

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import sports
from app.models.enums import ConsentPurpose, PlayerStatus
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.models.squad import Squad
from app.services.access import (
    Caller,
    consent_signature,
    consent_subquery,
    has_consent,
    may_view,
    visible_players,
)
from app.services.cohort import age_label
from app.services.views import organization_names

SPORT = "football"
MATCH = "football.match.v1"
SEASON = "football.season_aggregate.v2"
NAME_MAX = 80
CANDIDATE_LIMIT = 40

GK_NOTE = "Goalkeepers are not scored: there is no goalkeeping data."
NO_CONSENT = "No analytics consent in effect, so this player is not scored."
UNAVAILABLE = "Not available to you."


class SquadLabError(ValueError):
    """A request that does not describe a valid line-up. The message is safe to show."""


class NotFound(LookupError):
    pass


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def config() -> dict:
    raw = json.loads((sports.default_modules_dir() / "football.json").read_text(encoding="utf-8"))
    lab = raw["squadLab"]
    groups = raw["teamGaps"]["groups"]
    role_group = {role: name for name, spec in groups.items() for role in spec["roles"]}
    rules = {}
    for rule in lab["links"]:
        a, b = rule["between"]
        rules[(a, b)] = rule
    return {**lab, "roleGroup": role_group, "groupLabels": {k: v["label"] for k, v in groups.items()},
            "rules": rules, "roleNames": raw["roles"]["names"]}


def group_of(role: str | None) -> str | None:
    return config()["roleGroup"].get(role or "")


def _family(tier: str | None) -> str:
    return "academy" if tier == "youth" else "league"


def band(score: float | None) -> str:
    if score is None:
        return "unknown"
    bands = config()["bands"]
    return "green" if score >= bands["green"] else "yellow" if score >= bands["yellow"] else "red"


# ---------------------------------------------------------------------------
# Population: each consented player's raw trait values, and the ranking pools
# ---------------------------------------------------------------------------


@dataclass
class Record:
    schema: str
    family: str
    group: str | None
    minutes: float
    values: dict[str, float]  # trait -> raw value


@dataclass
class _Population:
    signature: tuple = ()
    records: dict[uuid.UUID, Record] = field(default_factory=dict)
    # (schema, family, group, trait) -> sorted raw values of players whose own group it is
    pools: dict[tuple, list[float]] = field(default_factory=dict)


_population = _Population()
_lock = threading.Lock()


def _signature(db: Session) -> tuple:
    rows = tuple(db.execute(select(func.count(), func.max(PerformanceEntry.updated_at))).one())
    people = tuple(db.execute(select(func.count(), func.max(Player.updated_at))).one())
    return (rows, people, consent_signature(db, ConsentPurpose.ANALYTICS.value), date.today())


def _value(source: dict, totals: dict, minutes: float) -> float | None:
    numerator = sum(float(totals.get(k) or 0) for k in source["numerator"])
    if "denominator" in source:
        denominator = sum(float(totals.get(k) or 0) for k in source["denominator"])
        return numerator / denominator if denominator > 0 else None
    if source.get("per90"):
        return numerator / minutes * 90 if minutes > 0 else None
    return numerator


def _record(schema: str, player: Player, totals: dict) -> Record | None:
    cfg = config()
    minutes = float(totals.get("minutes_played") or 0)
    if minutes < cfg["minMinutes"][schema]:
        return None
    values = {}
    for trait, spec in cfg["traits"].items():
        source = spec["sources"].get(schema)
        if source is None:
            continue
        value = _value(source, totals, minutes)
        if value is not None:
            values[trait] = value
    return Record(schema, _family(player.tier), group_of(player.position), minutes, values)


def _build(db: Session) -> _Population:
    cfg = config()
    consented = select(consent_subquery(ConsentPurpose.ANALYTICS.value).subquery().c.player_id)
    players = {
        p.id: p
        for p in db.execute(
            select(Player)
            .where(Player.status != PlayerStatus.MERGED)
            .where(Player.primary_sport == SPORT)
            .where(Player.id.in_(consented))
        ).scalars()
    }
    entries = db.execute(
        select(PerformanceEntry.player_id, PerformanceEntry.schema_ref, PerformanceEntry.period_start,
               PerformanceEntry.metrics)
        .where(PerformanceEntry.schema_ref.in_([MATCH, SEASON]))
        .where(PerformanceEntry.player_id.in_(list(players)))
    ).all() if players else []

    seasons: dict[uuid.UUID, tuple[date, dict]] = {}
    matches: dict[uuid.UUID, list[tuple[date, dict]]] = {}
    for player_id, schema, start, metrics in entries:
        if schema == SEASON:
            if player_id not in seasons or start > seasons[player_id][0]:
                seasons[player_id] = (start, metrics)
        else:
            matches.setdefault(player_id, []).append((start, metrics))

    records: dict[uuid.UUID, Record] = {}
    for player_id, player in players.items():
        record = None
        # A league season is the richer record; the academy match log is the fallback.
        if player_id in seasons:
            record = _record(SEASON, player, seasons[player_id][1])
        if record is None and player_id in matches:
            rows = matches[player_id]
            latest = max(start for start, _ in rows)
            since = latest - timedelta(days=cfg["matchWindowDays"])
            totals: dict[str, float] = {}
            for start, metrics in rows:
                if start > since:
                    for key, value in metrics.items():
                        if isinstance(value, (int, float)):
                            totals[key] = totals.get(key, 0) + value
            record = _record(MATCH, player, totals)
        if record is not None:
            records[player_id] = record

    pools: dict[tuple, list[float]] = {}
    for record in records.values():
        if record.group is None:
            continue
        for trait, value in record.values.items():
            pools.setdefault((record.schema, record.family, record.group, trait), []).append(value)
    for values in pools.values():
        values.sort()
    return _Population(records=records, pools=pools)


def population(db: Session) -> _Population:
    global _population
    signature = _signature(db)
    with _lock:
        if _population.signature != signature:
            built = _build(db)
            built.signature = signature
            _population = built
        return _population


def percentile(pool: list[float], value: float) -> float:
    """Share of the pool below the value, ties counted half. 0 to 100."""
    below = bisect.bisect_left(pool, value)
    equal = bisect.bisect_right(pool, value) - below
    return 100.0 * (below + equal / 2) / len(pool)


def trait_scores(pop: _Population, record: Record, slot_group: str, traits: list[str]) -> list[dict]:
    """Each trait the record has, ranked among the slot group's players of the same family."""
    cfg = config()
    out = []
    for trait in traits:
        value = record.values.get(trait)
        pool = pop.pools.get((record.schema, record.family, slot_group, trait))
        if value is None or pool is None or len(pool) < cfg["minPool"]:
            continue
        spec = cfg["traits"][trait]
        out.append({
            "trait": trait,
            "label": spec["label"],
            "measure": spec["sources"][record.schema]["label"],
            "value": round(value, 3),
            "percentile": round(percentile(pool, value)),
            "poolSize": len(pool),
        })
    return out


def _mean(scores: list[dict]) -> float | None:
    return round(fmean(s["percentile"] for s in scores), 1) if scores else None


# ---------------------------------------------------------------------------
# Evaluating a line-up
# ---------------------------------------------------------------------------


def formation(name: str) -> dict:
    formations = config()["formations"]
    if name not in formations:
        raise SquadLabError(f"Unknown formation {name!r}. Pick one of {', '.join(formations)}.")
    return formations[name]


def check_slots(formation_name: str, slots: dict[str, str | None]) -> dict[str, uuid.UUID]:
    """Validate a slot map and return it with parsed ids and empty slots dropped."""
    known = {slot["id"] for slot in formation(formation_name)["slots"]}
    out: dict[str, uuid.UUID] = {}
    for slot_id, player_id in slots.items():
        if slot_id not in known:
            raise SquadLabError(f"{formation_name} has no slot {slot_id!r}.")
        if not player_id:
            continue
        try:
            out[slot_id] = uuid.UUID(str(player_id))
        except ValueError:
            raise SquadLabError("Malformed player id.") from None
    if len(set(out.values())) != len(out):
        raise SquadLabError("A player can only stand in one slot.")
    return out


def _visible(db: Session, caller: Caller, ids: list[uuid.UUID]) -> dict[uuid.UUID, Player]:
    if not ids:
        return {}
    found = db.execute(
        visible_players(caller).where(Player.id.in_(ids)).where(Player.primary_sport == SPORT)
    ).scalars().unique()
    return {p.id: p for p in found if may_view(db, caller, p)[0]}


def _card(player: Player, clubs: dict, today: date) -> dict:
    return {
        "playerId": str(player.id), "fullName": player.full_name, "knownAs": player.known_as,
        "position": player.position, "tier": player.tier, "ageLabel": age_label(player.date_of_birth, today),
        "club": clubs.get(player.id), "isMinor": player.is_minor,
    }


def evaluate(db: Session, caller: Caller, formation_name: str, slots: dict[str, str | None]) -> dict:
    cfg = config()
    shape = formation(formation_name)
    chosen = check_slots(formation_name, slots)
    people = _visible(db, caller, list(chosen.values()))
    clubs = organization_names(db, list(people))
    pop = population(db)
    today = date.today()

    out_slots: dict[str, dict] = {}
    records: dict[str, Record | None] = {}
    for slot in shape["slots"]:
        sid, role = slot["id"], slot["role"]
        sgroup = group_of(role)
        entry = {"slotId": sid, "role": role, "roleName": cfg["roleNames"].get(role, role),
                 "x": slot["x"], "y": slot["y"], "state": "empty", "player": None, "fit": None,
                 "score": None, "band": "unknown", "traits": [], "note": None}
        out_slots[sid] = entry
        records[sid] = None
        if sid not in chosen:
            continue
        player = people.get(chosen[sid])
        if player is None:
            entry.update(state="unavailable", note=UNAVAILABLE)
            continue
        entry["player"] = _card(player, clubs, today)
        natural = group_of(player.position)
        entry["fit"] = ("unknown" if player.position is None else
                        "natural" if (natural == sgroup or player.position == role) else "out_of_position")
        if sgroup is None:
            entry.update(state="not_scored", note=GK_NOTE)
            continue
        record = pop.records.get(player.id)
        if record is None:
            if not has_consent(db, player.id, ConsentPurpose.ANALYTICS.value):
                entry.update(state="no_consent", note=NO_CONSENT)
            else:
                entry.update(state="no_data", note=_no_data_note())
            continue
        records[sid] = record
        scores = trait_scores(pop, record, sgroup, cfg["roleTraits"][sgroup])
        if not scores:
            entry.update(state="no_data", note="None of this position's numbers are in this player's record.")
            continue
        score = _mean(scores)
        entry.update(state="scored", score=score, band=band(score), traits=scores,
                     source="match records" if record.schema == MATCH else "latest league season",
                     rankedAmong=_ranked_among(record))
        if len(scores) <= 2:
            entry["note"] = f"Based on {len(scores)} number{'s' if len(scores) > 1 else ''} only."

    links = [_link(pop, out_slots, records, a, b) for a, b in shape["links"]]
    return {
        "formation": formation_name,
        "formations": list(cfg["formations"]),
        "slots": list(out_slots.values()),
        "links": links,
        "team": _team(out_slots, links),
        "caveats": _caveats(out_slots),
        "about": cfg["about"],
    }


def _ranked_among(record: Record) -> str:
    if record.schema == SEASON:
        return "league players with a season on record"
    return "academy players" if record.family == "academy" else "players outside the academies with match records"


def _no_data_note() -> str:
    cfg = config()
    return (f"Not enough minutes on record to score: at least {cfg['minMinutes'][MATCH]} academy match "
            f"minutes in a year, or {cfg['minMinutes'][SEASON]} in a league season.")


def _rule(group_a: str, group_b: str) -> tuple[dict | None, bool]:
    """The link rule for two slot groups, and whether it is written the other way round."""
    rules = config()["rules"]
    if (group_a, group_b) in rules:
        return rules[(group_a, group_b)], False
    if (group_b, group_a) in rules:
        return rules[(group_b, group_a)], True
    return None, False


def _link(pop: _Population, slots: dict, records: dict, a: str, b: str) -> dict:
    sa, sb = slots[a], slots[b]
    ga, gb = group_of(sa["role"]), group_of(sb["role"])
    out = {"from": a, "to": b, "label": None, "why": None, "score": None, "band": "unknown",
           "basis": {a: [], b: []}, "note": None, "keeper": False}
    if ga is None or gb is None:
        out.update(label="Goalkeeper", why="the keeper and his defenders", keeper=True,
                   note="Not scored: there is no goalkeeping data, so this line is always grey.")
        return out
    rule, flipped = _rule(ga, gb)
    if rule is None:
        out["note"] = "No rule for this pair of positions."
        return out
    out["label"], out["why"] = rule["label"], rule["why"]
    traits_a, traits_b = (rule["b"], rule["a"]) if flipped else (rule["a"], rule["b"])
    if records[a] is None or records[b] is None:
        out["note"] = ("Needs a player in both slots." if sa["player"] is None or sb["player"] is None
                       else "One of the two players has no score.")
        return out
    scores_a = trait_scores(pop, records[a], ga, traits_a)
    scores_b = trait_scores(pop, records[b], gb, traits_b)
    out["basis"] = {a: scores_a, b: scores_b}
    if not scores_a or not scores_b:
        out["note"] = "One side has none of the numbers this partnership needs."
        return out
    score = _mean(scores_a + scores_b)
    out.update(score=score, band=band(score))
    if len(scores_a) + len(scores_b) <= 3:
        out["note"] = f"Based on {len(scores_a) + len(scores_b)} numbers only."
    return out


def _team(slots: dict, links: list[dict]) -> dict:
    cfg = config()
    lines = []
    for key, spec in cfg["lines"].items():
        members = [s for s in slots.values() if group_of(s["role"]) in spec["groups"]]
        scored = [s["score"] for s in members if s["score"] is not None]
        enough = members and len(scored) * 2 >= len(members)
        lines.append({
            "key": key, "label": spec["label"], "slots": len(members), "scored": len(scored),
            "score": round(fmean(scored), 1) if enough else None,
            "band": band(round(fmean(scored), 1)) if enough else "unknown",
            "note": None if enough else f"Needs at least half of its {len(members)} players scored.",
        })
    # Keeper links are drawn but never scored, so they do not count against chemistry.
    scorable = [link for link in links if not link.get("keeper")]
    known = [link["score"] for link in scorable if link["score"] is not None]
    chem_ok = scorable and len(known) * 2 >= len(scorable)
    chemistry = {
        "score": round(fmean(known), 1) if chem_ok else None, "known": len(known), "links": len(scorable),
        "note": None if chem_ok else "Needs at least half of the links scored.",
    }
    chemistry["band"] = band(chemistry["score"])
    if all(line["score"] is not None for line in lines):
        weakest = min(lines, key=lambda line: line["score"])
        balance = {"score": weakest["score"], "band": weakest["band"], "weakest": weakest["label"],
                   "note": f"The weakest line, {weakest['label'].lower()}, sets the balance."}
    else:
        balance = {"score": None, "band": "unknown", "weakest": None,
                   "note": "Needs every line scored."}
    filled = sum(1 for s in slots.values() if s["player"] is not None)
    out_of_position = sum(1 for s in slots.values() if s["fit"] == "out_of_position")
    return {"lines": lines, "chemistry": chemistry, "balance": balance,
            "filled": filled, "slots": len(slots), "outOfPosition": out_of_position}


def _caveats(slots: dict) -> list[str]:
    out = [GK_NOTE]
    families = {s["player"]["tier"] == "youth" for s in slots.values() if s["player"]}
    if len(families) > 1:
        out.append("This line-up mixes academy and league players. Each is ranked against his own tier, "
                   "so an academy 80 is the top fifth of academy players, not of the league.")
    if any(s.get("source") == "match records" for s in slots.values()):
        out.append("Ranks are not adjusted for age: a 13-year-old is ranked against every academy player "
                   "in the position, older ones included.")
    thin = [s for s in slots.values() if s.get("source") == "match records"
            and group_of(s["role"]) in ("centre_backs", "full_backs", "holding_midfielders")]
    if thin:
        out.append("Match records have no interceptions, clearances, duels or headers, so a defender "
                   "scored from them is judged on tackles, passing and running alone.")
    return out


# ---------------------------------------------------------------------------
# Picking players for a slot
# ---------------------------------------------------------------------------


def candidates(db: Session, caller: Caller, role: str, query: str = "", exclude: list[str] | None = None,
               limit: int = CANDIDATE_LIMIT) -> dict:
    """Players the caller may see, best for this slot first. Unscored players come last."""
    cfg = config()
    if role not in cfg["roleNames"]:
        raise SquadLabError(f"Unknown position {role!r}.")
    sgroup = group_of(role)
    stmt = visible_players(caller).where(Player.primary_sport == SPORT)
    text = query.strip()
    if text:
        like = f"%{text}%"
        stmt = stmt.where(or_(Player.full_name.ilike(like), Player.known_as.ilike(like)))
    players = list(db.execute(stmt).scalars().unique())
    skip = set(exclude or [])
    pop = population(db)

    ranked = []
    for player in players:
        if str(player.id) in skip:
            continue
        record = pop.records.get(player.id)
        score = None
        if record is not None and sgroup is not None:
            score = _mean(trait_scores(pop, record, sgroup, cfg["roleTraits"][sgroup]))
        natural = group_of(player.position) == sgroup or player.position == role
        ranked.append((player, score, natural))
    # Natural position first, then the slot score, then the name: a manager filling a slot
    # wants the players who play there before the ones who could.
    ranked.sort(key=lambda r: (not r[2], r[1] is None, -(r[1] or 0), r[0].full_name))

    today = date.today()
    picked = []
    for player, score, natural in ranked:
        if len(picked) >= limit:
            break
        # Coaches' rows are already their own squad; scouts get the per-row consent check.
        if not may_view(db, caller, player)[0]:
            continue
        picked.append((player, score, natural))
    clubs = organization_names(db, [p.id for p, _, _ in picked])
    out = [{**_card(player, clubs, today), "score": score, "band": band(score), "naturalPosition": natural}
           for player, score, natural in picked]
    return {"role": role, "players": out}


# ---------------------------------------------------------------------------
# Saved squads (coaches only)
# ---------------------------------------------------------------------------


def may_save(caller: Caller) -> bool:
    return caller.is_coach and caller.organization_id is not None


def _squad_out(squad: Squad) -> dict:
    return {"id": str(squad.id), "name": squad.name, "formation": squad.formation,
            "slots": dict(squad.slots), "updatedAt": squad.updated_at.isoformat() if squad.updated_at else None}


def list_squads(db: Session, caller: Caller) -> list[dict]:
    if not may_save(caller):
        return []
    rows = db.execute(select(Squad).where(Squad.organization_id == caller.organization_id)
                      .order_by(Squad.updated_at.desc())).scalars()
    return [_squad_out(s) for s in rows]


def _owned(db: Session, caller: Caller, squad_id: uuid.UUID) -> Squad:
    squad = db.get(Squad, squad_id)
    if squad is None or not may_save(caller) or squad.organization_id != caller.organization_id:
        raise NotFound
    return squad


def get_squad(db: Session, caller: Caller, squad_id: uuid.UUID) -> dict:
    return _squad_out(_owned(db, caller, squad_id))


def _clean(db: Session, caller: Caller, name: str, formation_name: str, slots: dict) -> tuple[str, dict]:
    name = name.strip()[:NAME_MAX]
    if not name:
        raise SquadLabError("Give the squad a name.")
    chosen = check_slots(formation_name, slots)
    visible = _visible(db, caller, list(chosen.values()))
    if len(visible) != len(chosen):
        raise SquadLabError("Only players in your own squad can be saved in a line-up.")
    return name, {sid: str(pid) for sid, pid in chosen.items()}


def save_squad(db: Session, caller: Caller, name: str, formation_name: str, slots: dict,
               squad_id: uuid.UUID | None = None) -> dict:
    name, clean = _clean(db, caller, name, formation_name, slots)
    if squad_id is None:
        squad = Squad(organization_id=caller.organization_id, saved_by=caller.user_id, name=name,
                      sport=SPORT, formation=formation_name, slots=clean)
        db.add(squad)
    else:
        squad = _owned(db, caller, squad_id)
        squad.name, squad.formation, squad.slots, squad.saved_by = name, formation_name, clean, caller.user_id
    db.flush()
    db.refresh(squad)
    return _squad_out(squad)


def delete_squad(db: Session, caller: Caller, squad_id: uuid.UUID) -> None:
    db.delete(_owned(db, caller, squad_id))
    db.flush()
