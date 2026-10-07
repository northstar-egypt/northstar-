"""The table tennis rating on the player profile, from the graded model in ml/rating.

This file does not contain a model. It runs `ml/rating/points.py`, the point rating that
`python -m ml.run_rating_eval` grades against hidden ability (ml/README.md, "Table tennis
rating"), on the matches in this database. The rating a coach or scout sees is the rating
whose accuracy is published.

What is shown
-------------
A player's share of points against an average registered opponent of the same gender, with a
range (two standard errors either side), and what that share means over a best-of-five match.
Shown only when the range is at most 7 points in 100 wide (`points.SHOW_MAX_POINT_RANGE`);
otherwise the profile says there are not enough rated matches yet. Each match on the profile
also says how strong the opponent was going into that month, when that was known, and whether
the match counted toward the rating.

What counts
-----------
- Only confirmed matches move a rating: a row that is not self-submitted, or a match both
  players logged (ml/rating/matches.py). A self-submitted win nobody confirmed stays on the
  player's record and moves nobody's rating.
- Matches against outsiders count through one stand-in opponent per gender.
- **Analytics consent.** A player whose guardian has withdrawn analytics consent is not rated,
  and their matches are left out of everyone else's ratings too: rating an opponent from their
  points is still using their data for analytics.

Caching
-------
Fitting is fast at today's size (a few dozen players), but it is not free, and it does not
need to run on every request. The fits are kept until the table tennis rows or the consents
change, which is checked with two cheap queries per request.
TODO: at national scale (thousands of players) the dense solve in points.fit should become a
sparse one, and the monthly fits should be computed by a job rather than on request.
"""

from __future__ import annotations

import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.consent import Consent
from app.models.enums import ConsentPurpose, PlayerStatus
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.services.access import consent_subquery
from app.sports import impossibilities


def _make_ml_importable() -> None:
    """`ml/` sits at the repository root, beside `apps/`. The API image puts it on the path
    (see apps/api/Dockerfile); a local run from apps/api finds it by walking up."""
    try:
        import ml.rating  # noqa: F401
    except ImportError:
        for parent in Path(__file__).resolve().parents:
            if (parent / "ml" / "rating" / "points.py").is_file():
                sys.path.insert(0, str(parent))
                return


_make_ml_importable()

from ml.rating import points  # noqa: E402
from ml.rating.matches import _month, collect  # noqa: E402

SPORT = "table_tennis"
GENDER_WORDS = {"female": "girls and women", "male": "boys and men"}


@dataclass
class _Table:
    signature: tuple = ()
    # player id -> strength from every rated match
    now: dict[str, points.Strength] = field(default_factory=dict)
    # first day of a month -> player id -> strength from matches before that month
    by_month: dict[date, dict[str, points.Strength]] = field(default_factory=dict)
    # performance entry id -> whether its match counted toward ratings
    counted: dict[str, bool] = field(default_factory=dict)
    consented: set[str] = field(default_factory=set)
    # merged duplicate id -> the record it was merged into (followed to the end of the chain)
    survivor: dict[str, str] = field(default_factory=dict)

    def resolve(self, player_id) -> str:
        pid = str(player_id)
        return self.survivor.get(pid, pid)


_table = _Table()
_lock = threading.Lock()


def _signature(db: Session) -> tuple:
    rows = db.execute(
        select(func.count(), func.max(PerformanceEntry.updated_at)).where(
            PerformanceEntry.sport == SPORT
        )
    ).one()
    consents = db.execute(select(func.count(), func.max(Consent.updated_at))).one()
    return (tuple(rows), tuple(consents), date.today())


def _build(db: Session) -> _Table:
    consented = {
        str(pid) for (pid,) in db.execute(consent_subquery(ConsentPurpose.ANALYTICS.value)).all()
    }
    people = db.execute(
        select(Player.id, Player.sex, Player.status, Player.merged_into).where(
            Player.primary_sport == SPORT
        )
    ).all()
    merged_into = {str(pid): str(into) for pid, _, _, into in people if into is not None}

    def survivor(pid: str) -> str:
        # A duplicate's matches belong to the record it was merged into. Following the chain
        # (and stopping on a loop, which would be a data error) keeps a match against a merged
        # duplicate in the ratings instead of silently dropping it.
        seen = set()
        while pid in merged_into and pid not in seen:
            seen.add(pid)
            pid = merged_into[pid]
        return pid

    gender_of = {
        str(pid): sex
        for pid, sex, status, _ in people
        if status != PlayerStatus.MERGED.value
    }
    rows = []
    for e in db.execute(select(PerformanceEntry).where(PerformanceEntry.sport == SPORT)).scalars():
        player = survivor(str(e.player_id))
        opponent = survivor(str(e.opponent_player_id)) if e.opponent_player_id else None
        rows.append(
            {
                "id": str(e.id),
                "player_id": player,
                "opponent_player_id": opponent,
                "period_start": e.period_start,
                "metrics": e.metrics or {},
                "schema_ref": e.schema_ref,
                "source": e.source,
            }
        )
    # Leave out every row that involves a player without analytics consent, and any row that
    # after merging is a player against themselves (two records of one person cannot have
    # played each other; that is a data error, not a result).
    rows = [
        r
        for r in rows
        if r["player_id"] in consented
        and r["player_id"] in gender_of
        and (r["opponent_player_id"] is None or (
            r["opponent_player_id"] in consented
            and r["opponent_player_id"] in gender_of
            and r["opponent_player_id"] != r["player_id"]
        ))
        and "points_won" in r["metrics"]
    ]
    rows_by_id = {r["id"]: r for r in rows}
    matches = collect(rows)

    def fit(before: date | None) -> dict[str, points.Strength]:
        registered = [m for m in matches if before is None or m.played_on < before]
        evidence = points.point_matches(registered, rows_by_id)
        evidence += points.outsider_matches(rows, gender_of, before=before)
        return points.fit(evidence)

    table = _Table(
        consented=consented, survivor={pid: survivor(pid) for pid in merged_into}
    )
    table.now = fit(None)
    for month in sorted({_month(r["period_start"]) for r in rows}):
        table.by_month[month] = fit(month)
    for m in matches:
        for entry_id in m.entry_ids:
            table.counted[entry_id] = m.confirmed
    # A match against an outsider counts on the same terms as points.outsider_matches.
    for r in rows:
        if r["opponent_player_id"] is None:
            table.counted[r["id"]] = r["source"] != "self_submitted" and not impossibilities(
                r["metrics"], r["schema_ref"]
            )
    return table


def _current(db: Session) -> _Table:
    global _table
    signature = _signature(db)
    with _lock:
        if _table.signature != signature:
            table = _build(db)
            table.signature = signature
            _table = table
        return _table


def reset_cache() -> None:
    """For tests that change rows and need the next request to see it."""
    global _table
    with _lock:
        _table = _Table()


def surviving_id(db: Session, player_id) -> str:
    """The record a (possibly merged) player's matches are attributed to."""
    return _current(db).resolve(player_id)


def _share(strength: points.Strength) -> dict:
    low, high = strength.point_range
    return {"point_share": strength.point_share(), "low": low, "high": high}


def player_rating(db: Session, player: Player) -> dict | None:
    """The rating block for the profile. None for sports that have no rating."""
    if player.primary_sport != SPORT:
        return None
    table = _current(db)
    pid = table.resolve(player.id)
    population = f"registered {GENDER_WORDS.get(player.sex, 'players')} in table tennis"
    base = {"population": population, "rated_matches": 0, "shown": False}

    if pid not in table.consented:
        return {
            **base,
            "note": "No rating: analytics consent is not in effect for this player, so their "
            "matches are not used for ratings.",
        }
    strength = table.now.get(pid)
    if strength is None:
        return {
            **base,
            "note": "No rating yet: no confirmed matches against registered players or "
            "outsiders.",
        }
    rated = strength.matches
    if not strength.shown:
        return {
            **base,
            "rated_matches": rated,
            "note": f"Not enough rated matches yet to rate reliably ({rated} so far). A rating "
            "is shown once its range is narrower than 7 points in 100.",
        }
    return {
        **base,
        **_share(strength),
        "match_win": strength.match_win(),
        "rated_matches": rated,
        "shown": True,
        "note": None,
    }


def opponent_strengths(
    db: Session, entries: list[PerformanceEntry]
) -> dict[uuid.UUID, dict]:
    """For each table tennis entry: how strong the opponent was going into that month.

    Returns entry id -> {"strength": {...} or None, "counted": bool}. The strength is left out
    when the opponent was not yet rated reliably at the time, or has no analytics consent.
    Identity (who the opponent was) is not decided here: views.py checks whether the caller
    may see them.
    """
    if not any(e.sport == SPORT for e in entries):
        return {}
    table = _current(db)
    out = {}
    for e in entries:
        if e.sport != SPORT:
            continue
        strength = None
        if e.opponent_player_id is not None:
            then = table.by_month.get(_month(e.period_start), {}).get(
                table.resolve(e.opponent_player_id)
            )
            if then is not None and then.shown:
                strength = _share(then)
        out[e.id] = {"strength": strength, "counted": table.counted.get(str(e.id), False)}
    return out
