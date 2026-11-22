"""Find the next <pro>: academy players whose style looks like a professional's.

This file holds no method of its own. It reads the database and runs `ml/next_pro.py`, which
says how a match is made and what it cannot see; `python -m ml.next_pro_eval` measures how
stable the lists are.

- **Analytics consent.** Comparing a child with a professional is analytics on the child's
  data, so only academy players whose analytics consent is in effect are compared, and they
  alone make up the peer groups. The professional needs it too.
- **Who may see whom.** An academy player is listed only if the caller may see them
  (`access.may_view`), so a scout never learns from this list that a withheld minor exists.

TODO: at national scale the pools belong in a cached batch job, not a request.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ConsentPurpose, FootballTier, PlayerStatus
from app.models.measurement import Measurement
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.services import cohort
from app.services import forecast  # noqa: F401  (puts ml/ on the path)
from app.services import pro
from app.services.access import Caller, consent_subquery, has_consent, may_view

from ml import next_pro as N  # noqa: E402

YOUTH_SCHEMA = "football.match.v1"
NOTE = (
    "Style, not level: each academy player is judged against academy players of the same "
    "position and age, the professional against league players of the same position, and the "
    "two are compared on how they stand out. Compared on goals, assists, shots, shots on target, "
    "key passes, passes, tackles, pass completion and shot accuracy per 90, and lightly on "
    "height. The academy record has no dribbles, headers, interceptions, saves or speed, so "
    "those are not part of it. A high match says the styles are alike, not that the player "
    "will reach the same level."
)


def _heights(db: Session, ids: list) -> dict[str, float]:
    """Each player's latest height."""
    out: dict[str, tuple[date, float]] = {}
    if not ids:
        return {}
    for pid, on, value in db.execute(
        select(Measurement.player_id, Measurement.measured_at, Measurement.value)
        .where(Measurement.player_id.in_(ids), Measurement.metric == "height_cm")
    ).all():
        key = str(pid)
        if key not in out or on > out[key][0]:
            out[key] = (on, float(value))
    return {k: v for k, (_, v) in out.items()}


def _pros(db: Session) -> list[N.Player]:
    """Every professional's latest league season with enough minutes, one per player."""
    consented = {str(c) for c in db.execute(
        select(consent_subquery(ConsentPurpose.ANALYTICS.value).subquery().c.player_id)).scalars()}
    best = {}
    for r in pro._rows(db):
        if r.minutes < N.PRO_MIN_MINUTES or r.player_id not in consented:
            continue
        if r.player_id not in best or r.end > best[r.player_id].end:
            best[r.player_id] = r
    heights = _heights(db, list(best))
    out = []
    for r in best.values():
        raw = N.rates(r.metrics)
        if raw is None:
            continue
        if r.player_id in heights:
            raw["height_cm"] = heights[r.player_id]
        out.append(N.Player(r.player_id, r.position, (r.source,), raw))
    return out


def _youth(db: Session, before: date | None = None) -> list[N.Player]:
    """Every academy footballer with enough minutes, from match rows before `before` if given."""
    consented = select(consent_subquery(ConsentPurpose.ANALYTICS.value).subquery().c.player_id)
    players = {
        str(p.id): p for p in db.execute(
            select(Player).where(Player.tier == FootballTier.YOUTH.value,
                                 Player.primary_sport == "football",
                                 Player.status != PlayerStatus.MERGED,
                                 Player.id.in_(consented))
        ).scalars()
    }
    totals: dict[str, dict[str, float]] = {}
    if players:
        for pid, metrics in db.execute(
            select(PerformanceEntry.player_id, PerformanceEntry.metrics)
            .where(PerformanceEntry.schema_ref == YOUTH_SCHEMA,
                   PerformanceEntry.player_id.in_(list(players)),
                   *([PerformanceEntry.period_start < before] if before else []))
        ).all():
            t = totals.setdefault(str(pid), {})
            for k, v in (metrics or {}).items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    t[k] = t.get(k, 0) + v
    heights = _heights(db, list(totals))
    out = []
    for pid, t in totals.items():
        if t.get("minutes_played", 0) < N.YOUTH_MIN_MINUTES:
            continue
        raw = N.rates(t)
        if raw is None:
            continue
        if pid in heights:
            raw["height_cm"] = heights[pid]
        p = players[pid]
        year = str(p.date_of_birth.year) if p.date_of_birth else "unknown"
        out.append(N.Player(pid, p.position, (p.sex, year), raw))
    return out


def academy_matches(db: Session, caller: Caller, player: Player) -> dict:
    """The block for GET /players/{id}/academy-matches: a list, and a note that says what it is."""
    name = player.known_as or player.full_name
    if not has_consent(db, player.id, ConsentPurpose.ANALYTICS.value):
        return {"pro": name, "items": [], "note":
                "Analytics consent is not in effect for this player, so they are not compared."}
    if N.family(player.position) is None:
        return {"pro": name, "items": [], "note": (
            "Goalkeepers are not matched yet: the academy record has no saves or clean sheets."
            if player.position == "GK" else "This player has no outfield position on record.")}
    pros = _pros(db)
    me = next((p for p in pros if p.player_id == str(player.id)), None)
    if me is None:
        return {"pro": name, "items": [], "note": (
            pro.no_seasons_note(db, player) + f" Matching needs a league season of at least "
            f"{N.PRO_MIN_MINUTES} minutes with shots and passes.")}

    ranked = N.matches(me, pros, _youth(db), shown=200)
    if not ranked:
        return {"pro": name, "items": [], "note": (
            f"Too few to compare: matching needs at least {N.MIN_PEERS} league "
            f"{N.FAMILY_LABEL[N.family(me.position)]} and {N.MIN_PEERS} academy ones with "
            f"{N.YOUTH_MIN_MINUTES} minutes on record.")}
    style = N.pro_profile(me, pros)
    people = {str(p.id): p for p in db.execute(
        select(Player).where(Player.id.in_([m.player_id for m in ranked]))).scalars()}
    today = date.today()
    items = []
    for m in ranked:
        other = people.get(m.player_id)
        if other is None or not may_view(db, caller, other)[0]:
            continue
        items.append({
            "player_id": other.id,
            "full_name": other.full_name,
            "position": other.position,
            "age_label": cohort.age_label(other.date_of_birth, today),
            "percent": m.percent,
            "alike": [N.reason(k, style[k]) for k in m.alike],
            "differs": N.LABELS.get(m.differs) if m.differs else None,
        })
        if len(items) == N.SHOWN:
            break
    return {"pro": name, "items": items, "note": NOTE}
