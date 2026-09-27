"""Height forecasters: the two baselines the project is graded against, and the models.

Every forecaster answers one question: given what was known on the origin date, how tall
will this player be on a later date? "What was known" is a `Snapshot`, which holds only
measurements dated on or before the origin, for every player. Nothing in this module can
see past the origin, and that is the whole of what makes the walk-forward numbers honest.

Nothing here reads the generator
--------------------------------
The synthetic heights come from a growth curve in `data/pipelines/synthetic/growth.py`.
Importing that curve would forecast almost perfectly and prove nothing, the same way the
duplicate harness's `merged_into` control scores well by reading the answer. So every
population curve below is learned from the snapshot's own measurements, which is also what a
real deployment would have to do.

Stated age throughout, as in `ml/detectors/features.py`. The date of birth on the record is
all a deployment has, and a player lying about it will be forecast badly. That is a real
failure mode, not something to engineer away with information nobody would have.

The four forecasters
--------------------
  last value           height does not change. The baseline for "is the model adding
                       anything at all". Unbeatable for adults, which is why the headline is
                       reported on players who are still growing.

  population average   the median height for the player's sex and age on the target date.
                       Ignores everything about the individual. The baseline for "does knowing
                       this player's history help".

  cohort velocity      last value, plus how much the median player of that sex grows between
                       the two ages. Knows where the player is, and how fast children of that
                       age grow in general.

  centile tracking     the player keeps their position relative to their age group: a child on
                       the 30th centile at 12 is forecast on the 30th centile at 13. This is
                       how paediatric growth charts are read, and it is exactly the assumption
                       a late bloomer breaks. They slide down the centiles while their peers
                       spurt, then climb back, so this model runs tall for them through the
                       early teens (bias +1.0 cm across five seeds).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

DAYS_PER_YEAR = 365.25

# Half-year age buckets. Growth velocity changes quickly through the adolescent spurt, and
# whole-year buckets smear the peak across two years.
BUCKET_YEARS = 0.5
# Neighbouring buckets pooled either side before a bucket is judged too thin to use.
POOL_BUCKETS = 1
MIN_MEMBERS = 5

# Two readings closer than this give a velocity dominated by measurement noise: 0.55 cm of
# noise over a month is a growth rate of 13 cm a year in either direction.
MIN_VELOCITY_GAP_DAYS = 150

# The number of recent readings averaged to place a player on their centile. One reading
# carries its measurement noise straight into the forecast; three mostly cancel it.
CENTILE_READINGS = 3


def age_at(dob: date, when: date) -> float:
    return (when - dob).days / DAYS_PER_YEAR


def _bucket(age: float) -> float:
    return round(age / BUCKET_YEARS) * BUCKET_YEARS


@dataclass
class PlayerHistory:
    player_id: str
    sex: str
    dob: date
    # (date, cm), ascending, and only readings on or before the snapshot's origin.
    heights: list[tuple[date, float]]


@dataclass
class Curve:
    """A per-sex function of age, learned from bucketed observations.

    Stored as bucket centres with a median and spread each, linearly interpolated between
    centres, and held flat beyond the last centre on either side. Flat at the top end is
    the right behaviour for height (adults stop growing) and a safe one for velocity.
    """

    points: dict[str, list[tuple[float, float, float]]] = field(default_factory=dict)

    def at(self, sex: str, age: float) -> tuple[float, float] | None:
        points = self.points.get(sex)
        if not points:
            return None
        if age <= points[0][0]:
            return points[0][1], points[0][2]
        if age >= points[-1][0]:
            return points[-1][1], points[-1][2]
        for (a0, m0, s0), (a1, m1, s1) in zip(points, points[1:]):
            if a0 <= age <= a1:
                t = (age - a0) / (a1 - a0)
                return m0 + t * (m1 - m0), s0 + t * (s1 - s0)
        return None

    @classmethod
    def learn(
        cls, observations: dict[str, list[tuple[float, float]]], *, min_spread: float
    ) -> Curve:
        curve = cls()
        for sex, rows in observations.items():
            buckets: dict[float, list[float]] = defaultdict(list)
            for age, value in rows:
                buckets[_bucket(age)].append(value)
            points = []
            for centre in sorted(buckets):
                pooled: list[float] = []
                for offset in range(-POOL_BUCKETS, POOL_BUCKETS + 1):
                    pooled.extend(buckets.get(round(centre + offset * BUCKET_YEARS, 2), ()))
                if len(pooled) < MIN_MEMBERS:
                    continue
                spread = statistics.pstdev(pooled)
                points.append((centre, statistics.median(pooled), max(spread, min_spread)))
            curve.points[sex] = points
        return curve


class Snapshot:
    """Everything known on the origin date, and the population curves learned from it."""

    def __init__(self, origin: date, histories: dict[str, PlayerHistory]):
        self.origin = origin
        self.players = histories

        heights: dict[str, list[tuple[float, float]]] = defaultdict(list)
        velocities: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for history in histories.values():
            for when, cm in history.heights:
                heights[history.sex].append((age_at(history.dob, when), cm))
            for age, rate in _velocities(history):
                velocities[history.sex].append((age, rate))

        # The floor on the spread stops a bucket where everyone happens to be similar from
        # turning a normal child into an extreme centile.
        self.height_curve = Curve.learn(heights, min_spread=1.0)
        self.velocity_curve = Curve.learn(velocities, min_spread=0.2)

    def growth_between(self, sex: str, from_age: float, to_age: float) -> float:
        """Median growth in cm between two ages, integrating the learned velocity curve."""
        steps = max(1, int(abs(to_age - from_age) / 0.05))
        width = (to_age - from_age) / steps
        total = 0.0
        for index in range(steps):
            point = self.velocity_curve.at(sex, from_age + (index + 0.5) * width)
            if point is not None:
                # Negative median velocity is measurement noise in adults, not shrinking.
                total += max(point[0], 0.0) * width
        return total


def _velocities(history: PlayerHistory) -> list[tuple[float, float]]:
    """cm per year between readings far enough apart to mean something, at the midpoint age."""
    out = []
    readings = history.heights
    start = 0
    for end in range(1, len(readings)):
        gap = (readings[end][0] - readings[start][0]).days
        if gap < MIN_VELOCITY_GAP_DAYS:
            continue
        mid = readings[start][0] + (readings[end][0] - readings[start][0]) / 2
        rate = (readings[end][1] - readings[start][1]) / (gap / DAYS_PER_YEAR)
        out.append((age_at(history.dob, mid), rate))
        start = end
    return out


# ---------------------------------------------------------------------------
# Forecasters. Each takes the snapshot, one player, and a target date, and returns cm or
# None when it has nothing to go on. None is scored as a coverage gap, never as a guess.
# ---------------------------------------------------------------------------


def last_value(snapshot: Snapshot, history: PlayerHistory, target: date) -> float | None:
    return history.heights[-1][1] if history.heights else None


def population_average(
    snapshot: Snapshot, history: PlayerHistory, target: date
) -> float | None:
    point = snapshot.height_curve.at(history.sex, age_at(history.dob, target))
    return point[0] if point else None


def cohort_velocity(snapshot: Snapshot, history: PlayerHistory, target: date) -> float | None:
    if not history.heights:
        return None
    when, cm = history.heights[-1]
    return cm + snapshot.growth_between(
        history.sex, age_at(history.dob, when), age_at(history.dob, target)
    )


def centile_tracking(
    snapshot: Snapshot, history: PlayerHistory, target: date
) -> float | None:
    zs = []
    for when, cm in history.heights[-CENTILE_READINGS:]:
        point = snapshot.height_curve.at(history.sex, age_at(history.dob, when))
        if point:
            zs.append((cm - point[0]) / point[1])
    target_point = snapshot.height_curve.at(history.sex, age_at(history.dob, target))
    if not zs or target_point is None:
        return None
    median, spread = target_point
    return median + statistics.fmean(zs) * spread


FORECASTERS = {
    "baseline: last value": last_value,
    "baseline: population average": population_average,
    "cohort velocity": cohort_velocity,
    "centile tracking": centile_tracking,
}
