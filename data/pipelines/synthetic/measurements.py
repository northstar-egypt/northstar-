"""Biometric time-series.

Each measurement is the growth curve evaluated at the player's age *on that
date*, plus measurement noise. Two consequences fall out of that and both were
review points:

- the gap between readings carries information, because a reading eight months
  later is eight months further along the curve;
- adults do not grow, because the curve is flat past maturity. No special case,
  no clamp, it is just what the function does.

Age-fraud cases are generated from the player's true age while their recorded
date of birth says otherwise. The biometric outlier a detector should find is
therefore a real consequence of the planted fraud rather than a number nudged
upward by hand.
"""

from __future__ import annotations

from datetime import timedelta

from . import growth
from .config import GeneratorConfig
from .orm import Measurement, User, enums
from .players import PlayerProfile
from .rng import Rng

HEIGHT = "height_cm"
WEIGHT = "weight_kg"
SPRINT = "sprint_10m_s"


def _measurement_dates(rng: Rng, config: GeneratorConfig, profile: PlayerProfile):
    cfg = config.measurements
    end = config.population.reference_date
    months = rng.randint(cfg.min_history_months, cfg.max_history_months)
    start = end - timedelta(days=int(months * 30.44))

    dates = []
    cursor = start
    while cursor <= end:
        dates.append(cursor)
        cursor += timedelta(days=rng.randint(cfg.min_gap_days, cfg.max_gap_days))
    return dates


def generate_measurements(
    rng: Rng,
    config: GeneratorConfig,
    profiles: list[PlayerProfile],
    recorders: list[User],
) -> list[Measurement]:
    cfg = config.measurements
    rows: list[Measurement] = []

    # recorded_by must point at a human who plausibly logs measurements. Coaches
    # and admins only; a scout or a federation account never records one.
    valid_recorders = [
        u
        for u in recorders
        if u.role in (enums.UserRole.COACH.value, enums.UserRole.ADMIN.value)
    ]

    for profile in profiles:
        for when in _measurement_dates(rng, config, profile):
            # The body follows the true age. For everyone except planted fraud
            # cases the true age and the recorded age are the same number.
            age = profile.true_age(when)

            height = growth.height_cm(
                age, profile.sex, profile.adult_height_cm, profile.maturity_offset_years
            ) + rng.gauss(0, cfg.height_noise_cm)
            weight = growth.weight_kg(
                height, age, profile.sex, profile.build_offset
            ) + rng.gauss(0, cfg.weight_noise_kg)
            sprint = growth.sprint_10m_seconds(
                age, profile.sex, profile.talent_offset
            ) + rng.gauss(0, cfg.sprint_noise_s)

            self_submitted = rng.chance(cfg.self_submitted_fraction)
            source = (
                enums.MeasurementSource.SELF_SUBMITTED.value
                if self_submitted
                else enums.MeasurementSource.COACH_LOGGED.value
            )
            # Self-submitted readings have no coach behind them, which is also
            # the signal the integrity board cares about.
            recorded_by = None if self_submitted or not valid_recorders else rng.choice(valid_recorders).id
            confidence = (
                enums.MeasurementConfidence.ESTIMATED.value
                if rng.chance(cfg.estimated_confidence_fraction)
                else enums.MeasurementConfidence.MEASURED.value
            )

            for metric, value, unit in (
                (HEIGHT, round(height, 1), "cm"),
                (WEIGHT, round(weight, 1), "kg"),
                (SPRINT, round(sprint, 3), "s"),
            ):
                rows.append(
                    Measurement(
                        id=rng.uuid(),
                        player_id=profile.id,
                        measured_at=when,
                        metric=metric,
                        value=value,
                        unit=unit,
                        source=source,
                        recorded_by=recorded_by,
                        confidence=confidence,
                    )
                )

    return rows
