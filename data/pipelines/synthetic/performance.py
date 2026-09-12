"""Performance entries, with internally consistent metrics.

The review found 9 rows with zero minutes played but non-zero goals or shots, and
3 rows with more goals than shots. Those are not cosmetic. The fraud detector's
job is to separate planted fraud from ordinary data, and every impossible row in
the ordinary data is a false positive waiting to happen, or worse, a shortcut the
detector learns instead of learning fraud.

The fix is to generate causally rather than field by field. Minutes come first,
then shots as a rate over those minutes, then shots on target as a subset of
shots, then goals as a subset of those. An impossible row cannot be produced,
because the quantities are drawn from each other.

`assert_consistent` states the invariants in one place so the tests, and any
future contributor, can check a row without re-deriving them.
"""

from __future__ import annotations

from datetime import timedelta

from .config import GeneratorConfig
from .orm import Organization, PerformanceEntry, enums
from .players import PlayerProfile
from .rng import Rng

FOOTBALL_SCHEMA_REF = "football.match.v1"
FOOTBALL_SEASON_SCHEMA_REF = "football.season_aggregate.v1"
TABLE_TENNIS_SCHEMA_REF = "table_tennis.match.v1"

# Shots per 90 minutes by position, before the player's own ability multiplier.
_SHOT_RATE_PER_90 = {
    "GK": 0.02,
    "CB": 0.55,
    "LB": 0.45,
    "RB": 0.45,
    "CDM": 0.7,
    "CM": 1.1,
    "CAM": 2.0,
    "LW": 2.2,
    "RW": 2.2,
    "ST": 3.1,
}
_CONVERSION = {
    "GK": 0.02,
    "CB": 0.09,
    "LB": 0.07,
    "RB": 0.07,
    "CDM": 0.07,
    "CM": 0.09,
    "CAM": 0.11,
    "LW": 0.12,
    "RW": 0.12,
    "ST": 0.16,
}
_PASS_RATE_PER_90 = {
    "GK": 26,
    "CB": 62,
    "LB": 52,
    "RB": 52,
    "CDM": 68,
    "CM": 64,
    "CAM": 48,
    "LW": 34,
    "RW": 34,
    "ST": 26,
}


def assert_consistent(metrics: dict) -> None:
    """The invariants every football match row must satisfy.

    Raised as an assertion rather than returned as a warning: an inconsistent row
    is a bug in the generator, not a data quality tier.
    """
    minutes = metrics.get("minutes_played", 0)
    if minutes == 0:
        offenders = {
            k: v
            for k, v in metrics.items()
            if k != "minutes_played" and isinstance(v, (int, float)) and v != 0
        }
        assert not offenders, f"zero minutes but non-zero counting stats: {offenders}"
        return
    goals = metrics.get("goals", 0)
    on_target = metrics.get("shots_on_target", 0)
    shots = metrics.get("shots", 0)
    assert goals <= on_target <= shots, (
        f"goals ({goals}) <= shots_on_target ({on_target}) <= shots ({shots}) violated"
    )
    assert metrics.get("passes_completed", 0) <= metrics.get("passes_attempted", 0)
    assert 0 <= minutes <= 120


def _football_match_metrics(
    rng: Rng, profile: PlayerProfile, minutes: int, ability: float | None = None
) -> dict:
    if minutes == 0:
        # An unused substitute. Every counting stat is zero, by definition, and
        # this is the only branch that produces a zero-minute row.
        return {
            "minutes_played": 0,
            "shots": 0,
            "shots_on_target": 0,
            "goals": 0,
            "assists": 0,
            "key_passes": 0,
            "passes_attempted": 0,
            "passes_completed": 0,
            "tackles": 0,
            "distance_km": 0.0,
            "yellow_cards": 0,
            "red_cards": 0,
        }

    position = profile.position or "CM"
    share = minutes / 90.0
    # See PlayerProfile.effective_ability: equals `ability` for everyone except
    # planted age-fraud cases, who are competing below their development level.
    ability = profile.ability if ability is None else ability

    shots = rng.poisson(_SHOT_RATE_PER_90.get(position, 1.0) * ability * share)
    on_target = rng.binomial(shots, 0.38)
    goals = rng.binomial(on_target, _CONVERSION.get(position, 0.1) / 0.38)
    # binomial with p capped at 1 already guarantees goals <= on_target, but
    # state it rather than trust it.
    goals = min(goals, on_target)

    attempted = max(0, int(rng.gauss(_PASS_RATE_PER_90.get(position, 50) * share, 6 * share)))
    completed = rng.binomial(attempted, rng.uniform(0.68, 0.91))
    key_passes = rng.poisson(0.9 * ability * share)
    assists = rng.binomial(key_passes, 0.22)

    metrics = {
        "minutes_played": minutes,
        "shots": shots,
        "shots_on_target": on_target,
        "goals": goals,
        "assists": assists,
        "key_passes": key_passes,
        "passes_attempted": attempted,
        "passes_completed": completed,
        "tackles": rng.poisson(1.9 * share) if position != "GK" else 0,
        "distance_km": round(rng.gauss(10.4, 0.9) * share, 2) if position != "GK" else round(4.2 * share, 2),
        "yellow_cards": 1 if rng.chance(0.11 * share) else 0,
        "red_cards": 1 if rng.chance(0.006 * share) else 0,
    }
    assert_consistent(metrics)
    return metrics


def _table_tennis_metrics(rng: Rng, profile: PlayerProfile, ability: float) -> dict:
    sets_played = rng.randint(3, 7)
    sets_won = rng.binomial(sets_played, min(0.85, 0.35 + 0.2 * ability))
    points_played = sets_played * rng.randint(14, 22)
    points_won = rng.binomial(points_played, min(0.75, 0.4 + 0.12 * ability))
    metrics = {
        "sets_played": sets_played,
        "sets_won": min(sets_won, sets_played),
        "points_played": points_played,
        "points_won": min(points_won, points_played),
        "service_winners": rng.poisson(3.0 * ability),
        "unforced_errors": rng.poisson(9.0 / max(ability, 0.4)),
    }
    assert metrics["sets_won"] <= metrics["sets_played"]
    assert metrics["points_won"] <= metrics["points_played"]
    return metrics


def _draw_minutes(rng: Rng, config: GeneratorConfig) -> int:
    cfg = config.performance
    roll = rng.random.random()
    if roll < cfg.unused_sub_fraction:
        return 0
    if roll < cfg.unused_sub_fraction + cfg.substitute_fraction:
        return rng.randint(4, 42)
    return rng.choice([90, 90, 90, 88, 85, 78, 72, 65, 60])


def generate_performance_entries(
    rng: Rng,
    config: GeneratorConfig,
    profiles: list[PlayerProfile],
    orgs: list[Organization],
    affiliation_lookup: dict,
) -> list[PerformanceEntry]:
    cfg = config.performance
    reference = config.population.reference_date
    rows: list[PerformanceEntry] = []
    by_id = {o.id: o for o in orgs}

    for profile in profiles:
        own_org_id = affiliation_lookup.get(profile.id)
        own_org = by_id.get(own_org_id) if own_org_id else None
        # An opponent is any organization that is not the player's own. Never the
        # home org: a club does not play itself.
        opponent_pool = [
            o
            for o in orgs
            if o.id != own_org_id
            and o.type in (enums.OrganizationType.CLUB.value, enums.OrganizationType.ACADEMY.value)
            and o.sport in (profile.player.primary_sport, None)
        ]

        ability = profile.effective_ability(reference)
        n_entries = rng.randint(cfg.min_entries, cfg.max_entries)
        for _ in range(n_entries):
            days_back = rng.randint(0, 700)
            period_start = reference - timedelta(days=days_back)

            is_season = rng.chance(cfg.season_aggregate_fraction)
            if profile.player.primary_sport == enums.Sport.TABLE_TENNIS.value:
                metrics = _table_tennis_metrics(rng, profile, ability)
                schema_ref = TABLE_TENNIS_SCHEMA_REF
                period_type = enums.PeriodType.MATCH.value
                period_end = None
            elif is_season:
                appearances = rng.randint(8, 34)
                minutes_total = sum(_draw_minutes(rng, config) for _ in range(appearances))
                per_match = [
                    _football_match_metrics(rng, profile, _draw_minutes(rng, config), ability)
                    for _ in range(appearances)
                ]
                metrics = {
                    "appearances": appearances,
                    "minutes_played": minutes_total,
                    "goals": sum(m["goals"] for m in per_match),
                    "assists": sum(m["assists"] for m in per_match),
                    "shots": sum(m["shots"] for m in per_match),
                    "shots_on_target": sum(m["shots_on_target"] for m in per_match),
                }
                schema_ref = FOOTBALL_SEASON_SCHEMA_REF
                period_type = enums.PeriodType.SEASON_AGGREGATE.value
                period_end = period_start + timedelta(days=rng.randint(240, 300))
            else:
                metrics = _football_match_metrics(
                    rng, profile, _draw_minutes(rng, config), ability
                )
                schema_ref = FOOTBALL_SCHEMA_REF
                period_type = enums.PeriodType.MATCH.value
                period_end = None

            source = rng.choices(
                [
                    enums.PerformanceSource.API.value,
                    enums.PerformanceSource.SCRAPE.value,
                    enums.PerformanceSource.COACH_LOGGED.value,
                    enums.PerformanceSource.SELF_SUBMITTED.value,
                ],
                weights=[0.34, 0.22, 0.36, 0.08],
                k=1,
            )[0]

            rows.append(
                PerformanceEntry(
                    id=rng.uuid(),
                    player_id=profile.id,
                    sport=profile.player.primary_sport,
                    period_type=period_type,
                    period_start=period_start,
                    period_end=period_end,
                    organization_id=own_org.id if own_org else None,
                    opponent_org_id=rng.choice(opponent_pool).id if opponent_pool else None,
                    metrics=metrics,
                    schema_ref=schema_ref,
                    source=source,
                    is_validated=source
                    in (enums.PerformanceSource.API.value, enums.PerformanceSource.COACH_LOGGED.value),
                )
            )

    return rows
