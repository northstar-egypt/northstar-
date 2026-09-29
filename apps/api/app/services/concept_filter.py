"""Which players a concept from the search box (app/concepts.py) actually picks out.

Each concept is computed the way the rest of the platform already computes it, so the search
never claims something the profile would not show:

- Height and sprint: the latest reading's percentile against players of the same age and
  gender, exactly as the profile's percentile bars (services/cohort.py). Small for age is the
  bottom quarter of height, tall the top quarter, fast the quickest quarter of 10 m sprint
  times. A player whose cohort is too small for the profile to quote a percentile is never
  matched: the search does not know, so it does not say.
- Late bloomer: a live late-bloomer flag (open or awaiting information), the same ones the
  profile lists.
- A searchable sport statistic: the player's value from their own records, pooled as the
  profile pools it (sports.summarise), against everyone in the same kind of record and the
  same tier. Better quarter wins. Players with fewer records than the module's `minBasis`,
  or in a group smaller than the profile's minimum cohort, are never matched.

Concepts combine with AND, like every other filter.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import date

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app import sports
from app.concepts import Concept
from app.models.flag import Flag
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.services import cohort, flags, views

QUARTER = 25

_BODY = {
    "height_low": ("height_cm", lambda pct: pct <= QUARTER),
    "height_high": ("height_cm", lambda pct: pct >= 100 - QUARTER),
    # Lower sprint time is faster, so the fastest quarter has the lowest percentile.
    "sprint_fast": ("sprint_10m_s", lambda pct: pct <= QUARTER),
}


def matching_ids(
    db: Session, stmt: Select, wanted: list[Concept], today: date
) -> set[uuid.UUID]:
    """Players left by `stmt` that every concept in `wanted` picks out."""
    rows = db.execute(
        stmt.with_only_columns(
            Player.id, Player.sex, Player.date_of_birth, Player.primary_sport, Player.tier
        ).order_by(None)
    ).all()
    remaining = {row.id: row for row in rows}
    for concept in wanted:
        if not remaining:
            break
        if concept.kind in _BODY:
            keep = _body(db, remaining, concept.kind, today)
        elif concept.kind == "flag":
            keep = _flagged(db, set(remaining), concept.key)
        elif concept.kind == "stat":
            keep = _stat(db, remaining, concept)
        else:
            keep = set(remaining)  # a no-data concept never filters
        remaining = {pid: row for pid, row in remaining.items() if pid in keep}
    return set(remaining)


def _body(db: Session, rows: dict, kind: str, today: date) -> set[uuid.UUID]:
    metric, test = _BODY[kind]
    reference = cohort.get_reference(db)
    series = views.measurement_series(db, list(rows), metric)
    keep = set()
    for pid, row in rows.items():
        value = views.latest_value(series.get(pid))
        age = cohort.age_years(row.date_of_birth, today)
        if value is None or age is None:
            continue
        observations, _, _ = reference.cohort_for(metric, row.sex, age)
        if len(observations) < cohort.MIN_COHORT:
            continue
        if test(cohort.percentile_of(observations, value)):
            keep.add(pid)
    return keep


def _flagged(db: Session, ids: set[uuid.UUID], flag_type: str) -> set[uuid.UUID]:
    return set(
        db.execute(
            select(Flag.player_id)
            .where(Flag.player_id.in_(ids))
            .where(Flag.type == flag_type)
            .where(Flag.status.in_(flags.LIVE_STATUSES))
        ).scalars()
    )


# ---------------------------------------------------------------------------
# Sport statistics: every player's value, cached like the cohort reference
# ---------------------------------------------------------------------------

_TTL_SECONDS = 300
# (schema_ref, stat key) -> {player id: (value, basis)}
_stats: dict[tuple[str, str], dict[uuid.UUID, tuple[float, int]]] = {}
_stats_built = 0.0
_lock = threading.Lock()


def _build_stats(db: Session) -> dict:
    modules = sports.registry()
    by_player: dict[tuple[uuid.UUID, str], list[dict]] = {}
    for pid, ref, metrics in db.execute(
        select(PerformanceEntry.player_id, PerformanceEntry.schema_ref, PerformanceEntry.metrics)
    ):
        period = sports.period_for(ref, modules)
        if period is None or sports.validate(metrics, ref, modules):
            continue  # a record that fails its module does not count, as on the profile
        by_player.setdefault((pid, ref), []).append(metrics)
    table: dict[tuple[str, str], dict] = {}
    for (pid, ref), records in by_player.items():
        period = sports.period_for(ref, modules)
        for stat in sports.summarise(period, records):
            table.setdefault((ref, stat["key"]), {})[pid] = (stat["value"], stat["basis"])
    return table


def _stat_table(db: Session) -> dict:
    global _stats, _stats_built
    with _lock:
        if time.time() - _stats_built > _TTL_SECONDS:
            _stats = _build_stats(db)
            _stats_built = time.time()
        return _stats


def reset_cache() -> None:
    global _stats_built
    with _lock:
        _stats_built = 0.0


def _stat(db: Session, rows: dict, concept: Concept) -> set[uuid.UUID]:
    table = _stat_table(db)
    modules = sports.registry()
    tiers = dict(db.execute(select(Player.id, Player.tier)).all())
    keep = set()
    for sport in concept.sports:
        for ref, period in modules[sport].periods.items():
            spec = next((s for s in period.derived if s["key"] == concept.key), None)
            if spec is None or "search" not in spec:
                continue
            min_basis = spec["search"]["minBasis"]
            values = {
                pid: value
                for pid, (value, basis) in table.get((ref, concept.key), {}).items()
                if basis >= min_basis
            }
            groups: dict[str | None, list[float]] = {}
            for pid, value in values.items():
                groups.setdefault(tiers.get(pid), []).append(value)
            for pid in rows:
                if pid not in values:
                    continue
                group = sorted(groups.get(tiers.get(pid), []))
                if len(group) < cohort.MIN_COHORT:
                    continue
                pct = cohort.percentile_of(group, values[pid])
                better = pct >= 100 - QUARTER if concept.better == "higher" else pct <= QUARTER
                if better:
                    keep.add(pid)
    return keep
