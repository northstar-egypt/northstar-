"""Age-anchored growth curves.

The previous pass drifted each measurement upward from the last one by a random
amount in (0, 1.5) cm. That has three problems, and they are the same problem
seen from three angles: the drift is never negative, so 32-year-olds keep
growing; the drift is per reading, so two readings a week apart move as much as
two a year apart; and the height has no relationship to the player's age.

The fix is to stop modelling *change* and model the *value*: height is a
function of age, and a measurement is that function sampled on the measurement
date. Growth between two readings then falls out of the gap between their dates
for free, and an adult sits on the flat part of the curve and stops growing
without any special case.

The curve shape is a fraction-of-adult-height table by age, smoothed by linear
interpolation between knots. It is not a clinical growth standard and does not
need to be: it needs to be monotone, to saturate, to have an adolescent spurt
whose timing can be shifted, and to be documented as approximate.
"""

from __future__ import annotations

from datetime import date

# Fraction of adult stature by age, males. Roughly follows the shape of a
# CDC/WHO stature-for-age median: steady childhood growth, a spurt from about
# 12 to 16, then saturation. Approximate by design; see module docstring.
_MALE_FRACTION_KNOTS: list[tuple[float, float]] = [
    (0.0, 0.285),
    (2.0, 0.494),
    (4.0, 0.578),
    (6.0, 0.645),
    (8.0, 0.703),
    (10.0, 0.755),
    (11.0, 0.780),
    (12.0, 0.809),
    (13.0, 0.847),
    (14.0, 0.893),
    (15.0, 0.936),
    (16.0, 0.966),
    (17.0, 0.984),
    (18.0, 0.994),
    (19.0, 0.998),
    (20.0, 1.000),
]

# Females mature about two years earlier and saturate sooner.
_FEMALE_FRACTION_KNOTS: list[tuple[float, float]] = [
    (0.0, 0.305),
    (2.0, 0.525),
    (4.0, 0.615),
    (6.0, 0.687),
    (8.0, 0.752),
    (9.0, 0.788),
    (10.0, 0.824),
    (11.0, 0.866),
    (12.0, 0.909),
    (13.0, 0.947),
    (14.0, 0.973),
    (15.0, 0.988),
    (16.0, 0.996),
    (17.0, 0.999),
    (18.0, 1.000),
]

ADULT_HEIGHT_MEAN_CM = {"male": 175.5, "female": 162.5}
ADULT_HEIGHT_SD_CM = {"male": 6.4, "female": 5.9}

DAYS_PER_YEAR = 365.2425


def age_in_years(date_of_birth: date, on: date) -> float:
    """Exact age as a float, which is what the curves are indexed by."""
    return (on - date_of_birth).days / DAYS_PER_YEAR


def _interpolate(knots: list[tuple[float, float]], x: float) -> float:
    if x <= knots[0][0]:
        return knots[0][1]
    if x >= knots[-1][0]:
        return knots[-1][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return knots[-1][1]


def height_fraction(age: float, sex: str, maturity_offset_years: float = 0.0) -> float:
    """Fraction of adult stature reached at `age`.

    `maturity_offset_years` shifts the whole curve later in time. A positive
    offset is a late maturer: at 14 they are short for their cohort, and the
    spurt that their peers had at 13 arrives at 13 + offset. The curve still
    saturates at the same adult height, which is precisely why late bloomers are
    hard for a forecaster and worth planting as a labelled case.
    """
    knots = _FEMALE_FRACTION_KNOTS if sex == "female" else _MALE_FRACTION_KNOTS
    return _interpolate(knots, age - maturity_offset_years)


def height_cm(
    age: float,
    sex: str,
    adult_height_cm: float,
    maturity_offset_years: float = 0.0,
) -> float:
    """Expected stature in cm at a given age. Monotone in age, flat once adult."""
    return adult_height_cm * height_fraction(age, sex, maturity_offset_years)


def weight_kg(height: float, age: float, sex: str, build_offset: float = 0.0) -> float:
    """Weight derived from stature, so the two never contradict each other.

    Body mass index rises through adolescence and plateaus in adulthood; deriving
    weight from height and age keeps the pair coherent instead of letting a
    150 cm player weigh 90 kg.
    """
    base_bmi = 15.4 + 0.42 * min(age, 21.0)
    if sex == "female":
        base_bmi += 0.35
    bmi = base_bmi + build_offset
    metres = height / 100.0
    return bmi * metres * metres


def sprint_10m_seconds(age: float, sex: str, talent_offset: float = 0.0) -> float:
    """10 m sprint time. Improves with maturity, then plateaus.

    Lower is better, so this curve runs the opposite way to stature: the same
    saturation logic, expressed as a decreasing function.
    """
    fraction = height_fraction(age, sex)
    # 2.35 s at the very start of the curve down to about 1.72 s at maturity.
    base = 2.35 - 0.63 * fraction
    if sex == "female":
        base += 0.075
    return base + talent_offset


def draw_adult_height(rng, sex: str) -> float:
    return rng.gauss(ADULT_HEIGHT_MEAN_CM[sex], ADULT_HEIGHT_SD_CM[sex])
