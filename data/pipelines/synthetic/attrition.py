"""Simulated release: players who stop being measured because an academy let them go.

Off by default. The committed dataset, and every score already reported from it, is
unchanged unless `AttritionConfig.enabled` is set. It exists for one purpose: to test whether
a backtest can be fooled by the players who disappear.

Why it matters
--------------
A backtest scores what the system said in the past against what happened afterwards. In
real data, "what happened afterwards" only exists for players who were still being measured.
The players who were released stop generating rows, and they are not a random sample: an
academy that releases on size releases the small ones, which is where the late bloomers are.
A backtest run naively on the survivors is scored on exactly the players the system was
least needed for. Planting that bias here, with a record of who was released, lets
`ml/backtest.py` show how big the effect is and check that its dropout report catches it,
before real data can fool anyone.

The mechanism
-------------
Each football player is reviewed once, on the day they turn 14 by their *recorded* date of
birth, because that is the age an academy sees. Their most recent height is compared with
what is expected for that age and sex, and the probability of release rises the further
below expectation they are:

    p(release) = min(MAX_P, BASE_P + SLOPE_P * max(0, -z))

A released player's measurements and performance rows after the review date are removed.
Nothing else changes: affiliations are left as they are, so this variant is for evaluation
datasets and should not be loaded into the demo database.

The constants are a model of the practice, not a measurement of it. Nobody has published
Egyptian academy release rates by height, and these were set before the backtest was run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from . import growth
from .config import GeneratorConfig
from .orm import enums
from .players import PlayerProfile
from .rng import Rng

REVIEW_AGE = 14
BASE_P = 0.03
SLOPE_P = 0.30
MAX_P = 0.85

# A separate stream, so switching attrition on does not change a single other value in the
# dataset. Anything that consumed the main stream would shift every row generated after it.
_STREAM_OFFSET = 7919


@dataclass
class ReleaseCase:
    player_id: str
    released_on: date
    recorded_age: float
    height_cm: float
    height_z: float
    is_planted_late_bloomer: bool

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "released_on": self.released_on.isoformat(),
            "recorded_age": round(self.recorded_age, 2),
            "height_cm": round(self.height_cm, 1),
            "height_z": round(self.height_z, 2),
            "is_planted_late_bloomer": self.is_planted_late_bloomer,
        }


def _birthday(dob: date, years: int) -> date:
    try:
        return dob.replace(year=dob.year + years)
    except ValueError:  # 29 February
        return dob.replace(year=dob.year + years, day=28)


def expected_height(age: float, sex: str) -> tuple[float, float]:
    """Mean and spread of height at an age, from the generator's own curve.

    The generator is allowed to know its curve; it is what an academy's rough sense of "the
    right size for a 14 year old" stands in for. The forecasters are not, see ml/forecasting.
    """
    fraction = growth.height_fraction(age, sex)
    return (
        growth.ADULT_HEIGHT_MEAN_CM[sex] * fraction,
        growth.ADULT_HEIGHT_SD_CM[sex] * fraction,
    )


def apply_attrition(
    config: GeneratorConfig,
    profiles: list[PlayerProfile],
    measurements: list,
    performance_entries: list,
) -> tuple[list, list, list[ReleaseCase]]:
    """Release players at their review, and drop what would have been recorded afterwards."""
    rng = Rng(config.seed + _STREAM_OFFSET, config.name_locale)

    heights: dict = {}
    for m in measurements:
        if m.metric == "height_cm":
            heights.setdefault(m.player_id, []).append((m.measured_at, float(m.value)))

    released: dict = {}
    cases: list[ReleaseCase] = []
    for profile in profiles:
        player = profile.player
        if player.primary_sport != enums.Sport.FOOTBALL.value or player.date_of_birth is None:
            continue
        series = sorted(heights.get(profile.id, []))
        review = _birthday(player.date_of_birth, REVIEW_AGE)
        before = [(when, cm) for when, cm in series if when <= review]
        after = [when for when, _ in series if when > review]
        # Only players the academy was measuring on both sides of the review can be released
        # in the data. Anyone else was not at the academy at 14, as far as the record goes.
        if not before or not after:
            continue

        age = growth.age_in_years(player.date_of_birth, review)
        mean, spread = expected_height(age, profile.sex)
        z = (before[-1][1] - mean) / spread
        if rng.chance(min(MAX_P, BASE_P + SLOPE_P * max(0.0, -z))):
            released[profile.id] = review
            cases.append(
                ReleaseCase(
                    player_id=str(profile.id),
                    released_on=review,
                    recorded_age=age,
                    height_cm=before[-1][1],
                    height_z=z,
                    is_planted_late_bloomer=profile.is_planted_late_bloomer,
                )
            )

    kept_measurements = [
        m
        for m in measurements
        if m.player_id not in released or m.measured_at <= released[m.player_id]
    ]
    kept_performance = [
        e
        for e in performance_entries
        if e.player_id not in released or e.period_start <= released[e.player_id]
    ]
    return kept_measurements, kept_performance, cases
