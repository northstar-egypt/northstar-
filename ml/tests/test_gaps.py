"""Team gap analysis (ml/pro/gaps.py) and its reliability check (ml/pro/gap_eval.py).

The rules a scout relies on, on small hand-made leagues: the direction of every statistic, a
weakness only in the bottom third of a stable statistic, percentiles only within one league and
season and from enough players, and no player proposed for a weakness with no player link.
Then the config's measured flags, checked against the tuning seeds so they cannot drift.
"""

from __future__ import annotations

import statistics
from datetime import date

import pytest

from ml.pro import gap_eval, gaps
from ml.pro.seasons import SeasonRow
from ml.sport_modules import registry

CONFIG = registry()["football"].team_gaps
END = date(2026, 5, 31)
SEASON = "2025/26"
LEAGUE = "Test League"


def _team(club, *, xg_for=40.0, xg_against=40.0, set_for=8, matches=34):
    return gaps.TeamRow(club, LEAGUE, SEASON, {
        "matches": matches, "points": 45, "xg_for": xg_for, "xg_against": xg_against, "goals_for": 40,
        "goals_against": 40, "shots_against": 400, "possession_pct": 50.0, "set_piece_goals_for": set_for,
        "set_piece_goals_against": 8, "goals_against_last_15": 8,
    })


def _player(pid, club, *, position="ST", minutes=2000, npxg=5.0, shots=40, competition=LEAGUE):
    metrics = {"minutes_played": minutes, "npxg": npxg, "shots": shots, "xa": 2.0, "key_passes": 20,
               "passes_attempted": 600, "passes_completed": 480, "aerial_duels": 50, "aerial_duels_won": 25,
               "tackles": 10, "interceptions": 5, "clearances": 5, "crosses": 5, "dribbles_completed": 10,
               "duels": 200, "duels_won": 100}
    return SeasonRow(pid, SEASON, END, competition, club, position, date(2000, 1, 1), metrics)


def test_percentile_of_is_the_profiles_rule():
    assert gaps.percentile_of([1, 2, 3, 4], 5) == 99
    assert gaps.percentile_of([1, 2, 3, 4], 0) == 1
    assert gaps.percentile_of([1, 2, 3, 4], 2.5) == 50


def test_ranks_follow_each_statistics_direction_and_the_bottom_third_is_a_weakness():
    teams = [_team(f"c{i}", xg_for=30.0 + i, xg_against=30.0 + i) for i in range(9)]
    profile = {m.key: m for m in gaps.team_profile(CONFIG, teams, "c0", LEAGUE, SEASON)}
    assert profile["xg_for_per_game"].rank == 9 and profile["xg_for_per_game"].weak
    assert profile["xg_against_per_game"].rank == 1 and not profile["xg_against_per_game"].weak
    assert profile["xg_for_per_game"].of == 9


def test_an_unstable_statistic_in_the_bottom_third_is_shown_but_not_a_weakness():
    teams = [_team(f"c{i}", set_for=i) for i in range(9)]
    (metric,) = [m for m in gaps.team_profile(CONFIG, teams, "c0", LEAGUE, SEASON) if m.key == "set_pieces_for_per_game"]
    assert metric.rank == 9 and metric.bottom_unstable and not metric.weak
    assert gaps.club_needs(CONFIG, [metric], [], "c0", LEAGUE, SEASON) == {}


def test_too_few_teams_gives_no_rank():
    teams = [_team(f"c{i}", xg_for=30.0 + i) for i in range(gaps.MIN_COHORT - 1)]
    assert all(m.rank is None and not m.weak for m in gaps.team_profile(CONFIG, teams, "c0", LEAGUE, SEASON))


def test_candidates_come_from_other_clubs_with_enough_minutes_ranked_on_the_linked_statistics():
    rows = [_player(f"p{i}", f"c{i}", npxg=float(i), shots=10 * i) for i in range(10)]
    rows.append(_player("short", "c3", npxg=20.0, minutes=gaps.MIN_MINUTES - 1))
    need = gaps.candidates(CONFIG, rows, "strikers", ["npxg_per_90", "shots_per_90"],
                           competition=LEAGUE, season=SEASON, exclude_club="c9")
    ids = [c.player_id for c in need.candidates]
    assert "p9" not in ids and "short" not in ids
    assert ids[0] == "p8" and need.candidates[0].mean == need.candidates[0].percentiles["npxg_per_90"]
    assert need.candidates[0].population == 10


def test_a_population_too_small_gives_no_percentile_and_the_player_is_unranked():
    rows = [_player(f"p{i}", f"c{i}") for i in range(gaps.MIN_COHORT)]
    need = gaps.candidates(CONFIG, rows, "strikers", ["npxg_per_90"], competition=LEAGUE, season=SEASON)
    assert need.candidates == [] and len(need.unranked) == gaps.MIN_COHORT
    assert need.unranked[0].percentiles == {"npxg_per_90": None} and need.unranked[0].values["npxg_per_90"] > 0


def test_national_mode_ranks_each_player_only_within_their_own_league():
    home = [_player(f"h{i}", f"c{i}", npxg=float(i)) for i in range(10)]
    abroad = [_player(f"a{i}", f"x{i}", npxg=40.0, competition="League abroad (DE)") for i in range(2)]
    need = gaps.candidates(CONFIG, home + abroad, "strikers", ["npxg_per_90"], competition=None, season=None,
                           pool={"h9", "h1", "a0"})
    assert [c.player_id for c in need.candidates] == ["h9", "h1"]
    assert [c.player_id for c in need.unranked] == ["a0"]


def test_squad_coverage_splits_the_groups_minutes():
    rows = [_player(f"p{i}", f"c{i}") for i in range(9)]
    rows += [_player("mine2", "c0", minutes=500), _player("mine3", "c0", minutes=100)]
    (strikers,) = [g for g in gaps.squad_coverage(CONFIG, rows, "c0", LEAGUE, SEASON) if g.group == "strikers"]
    assert [p.player_id for p in strikers.players] == ["p0", "mine2", "mine3"]
    assert sum(p.share for p in strikers.players) == pytest.approx(1.0)
    assert strikers.players[-1].ranked is False and strikers.players[-1].percentiles["npxg_per_90"] is None
    assert strikers.players[0].percentiles["npxg_per_90"] is not None


def test_the_halves_are_two_seasons_of_17_matches_whose_goals_add_up():
    from data.pipelines.synthetic import pro_league as pl

    clubs, players = pl.synthetic_inputs(101, gap_eval.REFERENCE)
    first, second = pl.build_halves(101, clubs, players, gap_eval.REFERENCE)
    for half in (first, second):
        assert {t.metrics["matches"] for t in half.team_seasons} == {17}
        assert sum(r.metrics["goals"] for r in half.player_seasons) == sum(t.metrics["goals_for"] for t in half.team_seasons)
    again = pl.build_halves(101, clubs, players, gap_eval.REFERENCE)[0]
    assert [r.metrics for r in again.player_seasons] == [r.metrics for r in first.player_seasons]


@pytest.fixture(scope="module")
def tuning():
    return [gap_eval.halves(seed) for seed in (101, 202, 303)]


def test_the_configs_stability_flags_match_the_tuning_seeds(tuning):
    """The `stable` and `lowReliability` flags in football.json were set from this measurement.
    If the league or the statistics change, this fails until the flags are measured again."""
    for i, metric in enumerate(CONFIG.metrics):
        r = statistics.fmean(gap_eval.team_reliability(CONFIG, d)[i].r for d in tuning)
        assert metric.stable == (gap_eval.spearman_brown(r) >= gap_eval.TARGET), metric.key
    per = [gap_eval.player_reliability(CONFIG, d, gaps.MIN_MINUTES) for d in tuning]
    for key, attr in CONFIG.attributes.items():
        r = statistics.fmean(p[key][0] for p in per)
        assert attr.low_reliability == (gap_eval.spearman_brown(r) < 0.6), key


def test_the_minimum_minutes_is_what_the_tuning_seeds_choose(tuning):
    by_threshold = {}
    for threshold in gap_eval.THRESHOLDS:
        per = [gap_eval.player_reliability(CONFIG, d, threshold) for d in tuning]
        by_threshold[threshold] = {k: statistics.fmean(p[k][0] for p in per) for k in CONFIG.attributes}
    assert gap_eval.choose_min_minutes(by_threshold) == gaps.MIN_MINUTES
