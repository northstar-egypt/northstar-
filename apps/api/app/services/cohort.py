"""Population statistics: percentiles and the reference band behind a growth curve.

A number about a player only means something next to the population it is being compared
with, which is why `PercentileOut` carries a `population` string and why nothing in this file
returns a percentile without one.

Everything is computed from the rows currently in the database rather than from published
growth charts. That keeps the system honest about what it actually knows, and it is the
comparison a scout is really making when they say a player is big for their age. It also
means a thinly populated cohort produces a percentile from very few people, so
`MIN_COHORT` refuses rather than inventing one.

Cached per process
------------------
The reference is rebuilt at most once every `_TTL_SECONDS`. Recomputing it per request would
scan every measurement in the database on every profile view. A stale-by-minutes reference is
fine: a cohort median does not move when one player is measured.
"""

from __future__ import annotations

import statistics
import threading
import time
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.measurement import Measurement
from app.models.player import Player

DAYS_PER_YEAR = 365.25

# Below this many observations a cohort does not get a percentile at all. A "90th percentile
# of four people" is worse than no number, because it looks like a finding.
MIN_COHORT = 8

_TTL_SECONDS = 300

# Metrics the profile screen shows percentiles for, with how to label them and which
# direction is better. Sprint time is the one where lower wins, and getting that backwards
# would rank the fastest child last.
METRIC_DEFINITIONS: dict[str, tuple[str, str, bool]] = {
    "height_cm": ("Height", "cm", True),
    "weight_kg": ("Weight", "kg", True),
    "sprint_10m_s": ("10m sprint", "s", False),
}


@dataclass
class CohortReference:
    built_at: float = 0.0
    # (metric, sex, whole years of age) -> sorted observations
    buckets: dict[tuple[str, str, int], list[float]] = field(default_factory=dict)

    def cohort_for(
        self, metric: str, sex: str | None, age_years: float
    ) -> tuple[list[float], int, int]:
        """Observations for a cohort plus the age span they came from.

        Pooling the years either side matters at the top of the youth range, where the
        population thins out and a bucket would otherwise fall below `MIN_COHORT` and
        silently lose its percentiles. Height and speed change gradually with age, so
        comparing a 17-year-old against 16 to 18 is still comparing them against the right
        thing.

        The span comes back with the values because the caller has to say which population
        it used. Labelling a pooled cohort as a single age would be a small lie in the one
        field whose entire job is to stop a percentile being quoted without its population.
        """
        if sex is None:
            return [], 0, 0
        age = round(age_years)
        exact = self.buckets.get((metric, sex, age), [])
        if len(exact) >= MIN_COHORT:
            return exact, age, age
        pooled: list[float] = []
        for offset in (-1, 0, 1):
            pooled.extend(self.buckets.get((metric, sex, age + offset), []))
        return sorted(pooled), age - 1, age + 1

    def observations(self, metric: str, sex: str | None, age_years: float) -> list[float]:
        """Just the values, for callers that do not need to name the population."""
        return self.cohort_for(metric, sex, age_years)[0]


_reference = CohortReference()
_lock = threading.Lock()


def _build(db: Session) -> CohortReference:
    reference = CohortReference(built_at=time.time())
    rows = db.execute(
        select(
            Measurement.metric,
            Player.sex,
            Player.date_of_birth,
            Measurement.measured_at,
            Measurement.value,
        )
        .join(Player, Player.id == Measurement.player_id)
        .where(Measurement.metric.in_(tuple(METRIC_DEFINITIONS)))
        .where(Player.date_of_birth.is_not(None))
        .where(Player.sex.is_not(None))
    ).all()

    for metric, sex, dob, measured_at, value in rows:
        if value is None:
            continue
        age = (measured_at - dob).days / DAYS_PER_YEAR
        reference.buckets.setdefault((metric, sex, round(age)), []).append(float(value))

    for values in reference.buckets.values():
        values.sort()
    return reference


def get_reference(db: Session, *, force: bool = False) -> CohortReference:
    global _reference
    with _lock:
        if force or (time.time() - _reference.built_at) > _TTL_SECONDS:
            _reference = _build(db)
        return _reference


def reset_cache() -> None:
    """Drop the cached reference. Used by tests, which change the data underneath it."""
    global _reference
    with _lock:
        _reference = CohortReference()


# ---------------------------------------------------------------------------


def percentile_of(observations: list[float], value: float) -> int:
    """Where `value` sits in a sorted list, 1 to 99.

    Clamped away from 0 and 100 because neither is true of a real person: being the tallest
    player currently in the database is not being taller than everyone.
    """
    if not observations:
        return 50
    below = sum(1 for observation in observations if observation < value)
    equal = sum(1 for observation in observations if observation == value)
    fraction = (below + equal / 2) / len(observations)
    return max(1, min(99, round(fraction * 100)))


def quantiles(observations: list[float]) -> tuple[float, float, float] | None:
    """p25, p50 and p75 of a cohort, or None when it is too small to quote."""
    if len(observations) < MIN_COHORT:
        return None
    ordered = sorted(observations)
    p50 = statistics.median(ordered)
    midpoint = len(ordered) // 2
    lower = ordered[:midpoint]
    upper = ordered[midpoint + 1 :] if len(ordered) % 2 else ordered[midpoint:]
    p25 = statistics.median(lower) if lower else p50
    p75 = statistics.median(upper) if upper else p50
    return p25, p50, p75


def population_label(sex: str | None, age_low: int, age_high: int, count: int) -> str:
    """The sentence that goes under a percentile bar.

    Names the real age span, so a pooled cohort does not get reported as a single age.
    """
    who = {"male": "boys", "female": "girls"}.get(sex or "", "players")
    span = f"aged {age_low}" if age_low == age_high else f"aged {age_low} to {age_high}"
    return f"{count} {who} {span} in the database"


def age_years(dob: date | None, on: date) -> float | None:
    return (on - dob).days / DAYS_PER_YEAR if dob else None


def age_label(dob: date | None, on: date) -> str:
    """Age as a screen shows it. Months matter for a 12-year-old and not for a 27-year-old."""
    years = age_years(dob, on)
    if years is None:
        return "age unknown"
    if years < 18:
        whole = int(years)
        months = int(round((years - whole) * 12))
        if months == 12:
            whole, months = whole + 1, 0
        return f"{whole}y {months}m"
    return f"{int(years)}"
