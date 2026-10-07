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

import math
from datetime import timedelta

from .config import GeneratorConfig
from .orm import Organization, PerformanceEntry, enums, sports
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


def _play_table_tennis_match(rng: Rng, p_point: float, best_of: int) -> tuple[int, int, int, int]:
    """One finished match, played point by point, from side A's point of view.

    Returns sets won, sets lost, points won and points lost for side A. Playing the match
    makes every row a real result by construction: sets go to 11, win by 2, and the match
    stops as soon as one player reaches the winning number of sets. An earlier version drew
    the sets independently and the sport module rejected 681 of 681 rows.
    """
    target = best_of // 2 + 1
    sets_won = sets_lost = points_won = points_lost = 0
    while sets_won < target and sets_lost < target:
        mine = theirs = 0
        while not ((mine >= 11 or theirs >= 11) and abs(mine - theirs) >= 2):
            if rng.chance(p_point):
                mine += 1
            else:
                theirs += 1
        points_won += mine
        points_lost += theirs
        if mine > theirs:
            sets_won += 1
        else:
            sets_lost += 1
    return sets_won, sets_lost, points_won, points_lost


def _point_chance(ability: float, opponent_ability: float) -> float:
    """The chance that a player wins a point, from the gap in ability to the opponent.

    The gap is what decides a table tennis point; one player's ability alone says nothing
    about a result. One standard deviation of ability (0.28) is worth about 3 points in 100,
    which over a best of five is the difference between an even match and winning about two
    in three.
    """
    return min(0.70, max(0.30, 0.5 + 0.12 * (ability - opponent_ability)))


def _table_tennis_side(rng: Rng, ability: float, best_of: int, result: tuple) -> dict:
    sets_won, sets_lost, points_won, points_lost = result
    sets = sets_won + sets_lost
    return {
        "best_of": best_of,
        "sets_won": sets_won,
        "sets_lost": sets_lost,
        "points_won": points_won,
        "points_lost": points_lost,
        "service_winners": rng.poisson(0.6 * sets * ability),
        "unforced_errors": rng.poisson(2.0 * sets / max(ability, 0.4)),
    }


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
        if profile.player.primary_sport == enums.Sport.TABLE_TENNIS.value:
            continue  # played in pairs, on their own stream: generate_table_tennis_matches
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
            if is_season:
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

            source = _draw_source(rng)

            # Every generated row must pass its sport module. A failure here is a generator
            # bug, and it is raised now rather than left for the fraud detector to trip on as
            # a false positive. The planted fraud rows are added later, in planted.py, and are
            # the only rows in the dataset that fail.
            problems = sports.validate(metrics, schema_ref)
            assert not problems, f"{schema_ref} row fails its sport module: {problems}"

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
                    is_validated=_is_trusted(source),
                )
            )

    table_tennis = [
        p for p in profiles if p.player.primary_sport == enums.Sport.TABLE_TENNIS.value
    ]
    rows += generate_table_tennis_matches(config, table_tennis, orgs, affiliation_lookup)
    return rows


def _draw_source(rng: Rng) -> str:
    return rng.choices(
        [
            enums.PerformanceSource.API.value,
            enums.PerformanceSource.SCRAPE.value,
            enums.PerformanceSource.COACH_LOGGED.value,
            enums.PerformanceSource.SELF_SUBMITTED.value,
        ],
        weights=[0.34, 0.22, 0.36, 0.08],
        k=1,
    )[0]


def _is_trusted(source: str) -> bool:
    return source in (enums.PerformanceSource.API.value, enums.PerformanceSource.COACH_LOGGED.value)


# Table tennis matches draw from their own stream, so a change to how they are played never
# shifts a football row, a height reading or a planted case again. Moving them here shifted
# the main stream once; see docs/decisions/0004-table-tennis-opponent-strength.md.
_TT_STREAM_OFFSET = 104729

# Share of a player's matches against someone who is not on the platform: a club player from
# abroad, or a child whose guardian never signed them up. Those matches count toward results
# but not toward a rating, and the row stores nothing about who the opponent was.
TT_EXTERNAL_SHARE = 1 / 3
# Share of matches between two registered players that only one of them logged.
TT_MISSING_MIRROR = 0.12
# How fast the chance of meeting someone falls with the gap in recorded age, in years. Draws
# and leagues go by age group, so juniors mostly meet juniors. Age and gender decide who meets
# whom, not ability, so a raw win rate is not handicapped by design.
TT_AGE_SCALE_YEARS = 3.0


def generate_table_tennis_matches(
    config: GeneratorConfig,
    profiles: list[PlayerProfile],
    orgs: list[Organization],
    affiliation_lookup: dict,
) -> list[PerformanceEntry]:
    """Matches between two players, written once per side, plus matches against outsiders.

    A match between two registered players is played once and written as two mirrored rows:
    one player's sets won are the other's sets lost, and each row names the other player in
    `opponent_player_id`. Service winners and unforced errors are each player's own.

    Who wins a point depends on the gap in ability between the two (`_point_chance`), so a
    result means something only next to who it was against. That is what the rating in
    `ml/rating` is built to recover, and each player's hidden ability is in the ground truth
    so the rating can be graded.
    """
    rng = Rng(config.seed + _TT_STREAM_OFFSET, config.name_locale)
    cfg = config.performance
    reference = config.population.reference_date
    by_org = {o.id: o for o in orgs}
    ability = {p.id: p.effective_ability(reference) for p in profiles}
    rows: list[PerformanceEntry] = []

    def emit(profile, metrics, played_on, opponent=None, opponent_org_id=None):
        problems = sports.validate(metrics, TABLE_TENNIS_SCHEMA_REF)
        assert not problems, f"{TABLE_TENNIS_SCHEMA_REF} row fails its sport module: {problems}"
        own_org = by_org.get(affiliation_lookup.get(profile.id))
        source = _draw_source(rng)
        rows.append(
            PerformanceEntry(
                id=rng.uuid(),
                player_id=profile.id,
                sport=profile.player.primary_sport,
                period_type=enums.PeriodType.MATCH.value,
                period_start=played_on,
                period_end=None,
                organization_id=own_org.id if own_org else None,
                opponent_org_id=opponent_org_id,
                opponent_player_id=opponent.id if opponent else None,
                metrics=metrics,
                schema_ref=TABLE_TENNIS_SCHEMA_REF,
                source=source,
                is_validated=_is_trusted(source),
            )
        )

    for profile in profiles:
        rivals = [p for p in profiles if p.id != profile.id and p.player.sex == profile.player.sex]
        age = profile.recorded_age(reference)
        weights = [
            math.exp(-abs(age - r.recorded_age(reference)) / TT_AGE_SCALE_YEARS) for r in rivals
        ]
        own_org_id = affiliation_lookup.get(profile.id)
        clubs = [
            o
            for o in orgs
            if o.id != own_org_id
            and o.type in (enums.OrganizationType.CLUB.value, enums.OrganizationType.ACADEMY.value)
            and o.sport in (enums.Sport.TABLE_TENNIS.value, None)
        ]
        # Each registered match gives both players a row, so a player starts about 60% of the
        # matches the old one-sided generator gave them and ends with about as many rows.
        n_matches = round(rng.randint(cfg.min_entries, cfg.max_entries) * 0.6)
        for _ in range(n_matches):
            played_on = reference - timedelta(days=rng.randint(0, 700))
            best_of = 7 if rng.chance(0.3) else 5
            mine = ability[profile.id]
            if not rivals or rng.chance(TT_EXTERNAL_SHARE):
                # An outsider, drawn from the whole population, not matched to this player.
                theirs = max(0.25, rng.gauss(1.0, 0.28))
                result = _play_table_tennis_match(rng, _point_chance(mine, theirs), best_of)
                emit(
                    profile,
                    _table_tennis_side(rng, mine, best_of, result),
                    played_on,
                    opponent_org_id=rng.choice(clubs).id if clubs else None,
                )
                continue

            rival = rng.choices(rivals, weights=weights, k=1)[0]
            theirs = ability[rival.id]
            won, lost, pts_won, pts_lost = _play_table_tennis_match(
                rng, _point_chance(mine, theirs), best_of
            )
            rival_org_id = affiliation_lookup.get(rival.id)
            clubmates = rival_org_id == own_org_id
            sides = [
                (profile, _table_tennis_side(rng, mine, best_of, (won, lost, pts_won, pts_lost)),
                 rival, None if clubmates else rival_org_id),
                (rival, _table_tennis_side(rng, theirs, best_of, (lost, won, pts_lost, pts_won)),
                 profile, None if clubmates else own_org_id),
            ]
            if rng.chance(TT_MISSING_MIRROR):
                sides.pop(rng.randint(0, 1))  # one of the two never logged it
            for player, metrics, opponent, opponent_org_id in sides:
                emit(player, metrics, played_on, opponent=opponent, opponent_org_id=opponent_org_id)
    return rows
