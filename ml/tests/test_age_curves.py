"""Per-position age curves (ml/pro/age_curves.py), checked on invented players only.

The simulated leagues below have a known age curve, so the tests can say what the delta method
must give back, and where the simple average by age must go wrong. No real player data is read
or written here; the cache loader is tried on a tiny cache made up in a temporary folder.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from ml import figure_age_curves as figure
from ml.pro import age_curves as ac
from ml.pro.age_curves import SeasonRecord

SEPT_1 = date(2018, 9, 1)


def _stamp(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _row(pid=1, *, birthday=date(1996, 3, 1), position="Midfielder", minutes=2000, goals=5, assists=3, age=99, **extra):
    return {"id": pid, "birthday": _stamp(birthday) if isinstance(birthday, date) else birthday,
            "position": position, "minutes_played_overall": minutes, "goals_overall": goals,
            "assists_overall": assists, "age": age} | extra


def _rec(pid, year, age, *, position="midfielder", minutes=2000, goals=5, assists=3):
    return SeasonRecord(pid, year, position, age, minutes, goals, assists)


# ----- age: from the birthday, never the `age` field -------------------------------------------

def test_age_comes_from_the_birthday_on_1_september_not_the_age_field():
    report = ac.LoadReport()
    # Born 1992-03-01: 26 on 1 September 2018. The file's `age` (33, the age at download) is ignored.
    record = ac.record_from_row(_row(birthday=date(1992, 3, 1), age=33), 2018, report)
    assert record.age == 26


@pytest.mark.parametrize("birthday, expected", [
    (date(1992, 8, 31), 26),   # already 26 on 1 September
    (date(1992, 9, 1), 26),    # turns 26 on that very day
    (date(1992, 9, 2), 25),    # still 25
    (date(1992, 12, 31), 25),
])
def test_age_on_the_first_of_september_boundaries(birthday, expected):
    assert ac.age_on_first_of_september(birthday, 2018) == expected


def test_the_same_birthday_is_a_year_older_in_the_next_season():
    assert ac.age_on_first_of_september(date(1992, 3, 1), 2019) == 27


# ----- leaving players out, and counting them ---------------------------------------------------

def test_every_row_is_used_or_counted_with_its_reason():
    report = ac.LoadReport()
    rows = [
        _row(1),
        _row(2, position="Coach"),
        _row(3, birthday=0),
        _row(4, birthday=-1),
        _row(5, birthday=None),
        _row(6, minutes=0),
        _row(7, minutes=-1),
        _row(8, position="Referee"),
        _row(9, goals=None),
    ]
    kept = [ac.record_from_row(r, 2018, report) for r in rows]
    assert [k is not None for k in kept] == [True] + [False] * 8
    assert report.rows_read == 9 and report.used == 1
    assert report.left_out["not a player (coach)"] == 1
    assert report.left_out["no birthday"] == 3
    assert report.left_out["never played (0 minutes)"] == 1
    assert report.left_out["missing fields"] == 2
    assert report.left_out["unknown position"] == 1
    assert report.used + sum(report.left_out.values()) == report.rows_read


def test_per90_needs_900_minutes_but_the_minutes_share_does_not():
    short = _rec(1, 2018, 22, minutes=899, goals=3)
    assert ac.measure_value(short, "goals_per90") is None
    assert ac.measure_value(short, "assists_per90") is None
    assert ac.measure_value(short, "minutes_share") == pytest.approx(899 / 3420)
    assert ac.measure_value(_rec(1, 2018, 22, minutes=900, goals=10), "goals_per90") == pytest.approx(1.0)


def test_goalkeepers_get_the_minutes_curve_only():
    assert ac.measures_for("goalkeeper") == ("minutes_share",)
    assert ac.measures_for("forward") == ac.MEASURES


# ----- pairs ------------------------------------------------------------------------------------

def test_a_player_makes_one_pair_per_consecutive_season_and_none_across_a_gap():
    records = [_rec(1, 2018, 20), _rec(1, 2019, 21), _rec(1, 2020, 22), _rec(2, 2018, 25), _rec(2, 2020, 27)]
    pairs = ac.consecutive_pairs(records)
    assert [(p.player_id, p.first.start_year, p.age) for p in pairs] == [(1, 2018, 20), (1, 2019, 21)]


def test_empty_and_single_player_input_make_no_curve():
    assert ac.build_curve([], "midfielder", "minutes_share", n_bootstrap=0) is None
    one = [_rec(1, 2018, 20), _rec(1, 2019, 21)]
    assert ac.build_curve(one, "midfielder", "minutes_share", n_bootstrap=0) is None  # one pair < 30


# ----- the delta method recovers a known curve --------------------------------------------------

def _noiseless_league(true_delta: dict[int, float], players_per_age: int, *, position="midfielder"):
    """Players whose goals per 90 change by exactly true_delta[age] from age to age + 1. Minutes
    differ from player to player, so the weights are not all equal, but the change does not depend on
    them, so any weighting must give the same answer."""
    records = []
    pid = 0
    for age, delta in true_delta.items():
        for k in range(players_per_age):
            pid += 1
            minutes = 1500 + 17 * k
            level = 0.2 + 0.001 * (k % 7)
            records.append(_goals_record(pid, 2018, position, age, minutes, level))
            records.append(_goals_record(pid, 2019, position, age + 1, minutes + 100, level + delta))
    return records


def _goals_record(pid, year, position, age, minutes, per90):
    # Goals are a float on purpose, so the rate is exactly per90 and the test can demand exact changes.
    return SeasonRecord(pid, year, position, age, minutes, per90 * minutes / 90, 0)


def test_noiseless_changes_are_recovered_exactly_whatever_the_weights():
    true_delta = {20: 0.03, 21: 0.02, 22: 0.01, 23: 0.0, 24: -0.01}
    records = _noiseless_league(true_delta, players_per_age=30)
    curve = ac.build_curve(records, "midfielder", "goals_per90", n_bootstrap=0)
    assert curve.ages == [20, 21, 22, 23, 24]
    assert curve.delta == pytest.approx(list(true_delta.values()))
    assert curve.pairs == [30] * 5
    # The curve is the changes added up from the youngest age.
    steps = np.diff(curve.level)
    assert steps == pytest.approx(list(true_delta.values()))


def test_an_age_with_fewer_than_30_pairs_is_not_drawn_and_a_gap_ends_the_curve():
    true_delta = {20: 0.03, 21: 0.02, 22: 0.01, 24: 0.0, 25: 0.0, 26: 0.0, 27: 0.0}
    records = _noiseless_league(true_delta, players_per_age=30)
    # Age 22 keeps only 29 players, so the run 20, 21 is broken and the longer run 24..27 is used.
    drop = {r.player_id for r in records if r.age == 22 and r.start_year == 2018}
    for pid in sorted(drop)[:1]:
        records = [r for r in records if r.player_id != pid]
    curve = ac.build_curve(records, "midfielder", "goals_per90", n_bootstrap=0)
    assert curve.ages == [24, 25, 26, 27]
    assert 22 in curve.ages_left_out and curve.ages_left_out[22] == 29
    assert curve.delta_at(23) is None and curve.delta_at(25) == pytest.approx(0.0)


def test_pairs_are_weighted_by_the_smaller_of_the_two_seasons_minutes():
    # Two kinds of pair at one age: a long-minutes pair that rose by 0.1 and a short-minutes pair
    # that fell by 0.1, 30 of each, weights 3000 and 1000. Weighted mean: (3000 * 0.1 - 1000 * 0.1) / 4000.
    records = []
    for k in range(30):
        records += [_goals_record(k, 2018, "forward", 25, 3000, 0.4), _goals_record(k, 2019, "forward", 26, 3400, 0.5)]
        records += [_goals_record(100 + k, 2018, "forward", 25, 1000, 0.4), _goals_record(100 + k, 2019, "forward", 26, 1200, 0.3)]
    curve = ac.build_curve(records, "forward", "goals_per90", n_bootstrap=0)
    assert curve.delta == pytest.approx([(3000 * 0.1 - 1000 * 0.1) / 4000])


# ----- a simulated league: truth, band, survivorship --------------------------------------------

def _simulate(truth, n_players, seed, *, leave_below=None, years=range(2018, 2025), position="midfielder"):
    """Poisson goals around ability + truth(age). With `leave_below`, a player whose ability is below
    leave_below(age) is not in the league that season (so the weaker players drop out with age)."""
    rng = np.random.default_rng(seed)
    records = []
    for pid in range(n_players):
        ability = rng.uniform(0.15, 0.45)
        start_age = int(rng.integers(18, 34))
        for year in years:
            age = start_age + (year - years[0])
            if leave_below is not None and ability < leave_below(age):
                break
            minutes = int(rng.integers(1500, 3400))
            rate = max(0.01, ability + truth(age))
            records.append(SeasonRecord(pid, year, position, age, minutes, int(rng.poisson(rate * minutes / 90)), 0))
    return records


def _truth(age):  # rises to 26, then falls; mild enough that no simulated rate is clipped at its floor
    return -0.0005 * (age - 26) ** 2


def test_the_delta_curve_recovers_a_known_age_curve_and_the_band_holds_it():
    records = _simulate(_truth, 8000, seed=1)
    curve = ac.build_curve(records, "midfielder", "goals_per90", n_bootstrap=200, seed=1)
    true_steps = [_truth(a + 1) - _truth(a) for a in curve.ages]
    assert curve.delta == pytest.approx(true_steps, abs=0.02)
    true_level = np.concatenate([[0], np.cumsum(true_steps)])
    got_level = np.array(curve.level) - curve.level[0]
    assert np.abs(got_level - true_level).max() < 0.06
    # The band brackets the curve, is wider where there are fewer players, and never has a negative width.
    assert all(lo <= mid <= hi for lo, mid, hi in zip(curve.low, curve.level, curve.high))
    widths = np.array(curve.high) - np.array(curve.low)
    assert widths[-1] > widths[1]


def test_the_same_seed_gives_the_same_band():
    records = _simulate(_truth, 800, seed=2)
    a = ac.build_curve(records, "midfielder", "goals_per90", n_bootstrap=50, seed=7)
    b = ac.build_curve(records, "midfielder", "goals_per90", n_bootstrap=50, seed=7)
    assert a.low == b.low and a.high == b.high


def test_the_simple_average_rises_late_only_because_weaker_players_leave():
    # After 30 every player's true level falls, but players below a rising ability bar leave the league.
    def decline(age):
        return -0.01 * max(0, age - 30)

    def bar(age):
        return 0.15 + 0.03 * max(0, age - 30)

    records = _simulate(decline, 6000, seed=3, leave_below=bar)
    simple = ac.simple_average(records, "midfielder", "goals_per90")
    curve = ac.build_curve(records, "midfielder", "goals_per90", n_bootstrap=0)
    old, young = max(a for a in simple if a <= 36), 30
    assert simple[old][0] > simple[young][0]            # the simple average rises after 30
    assert curve.level[curve.ages.index(old)] < curve.level[curve.ages.index(young)]   # the curve falls


def test_simple_average_leaves_out_ages_with_too_few_players():
    records = [_rec(i, 2018, 20, goals=9) for i in range(29)] + [_rec(i, 2018, 21, goals=9) for i in range(30)]
    assert sorted(ac.simple_average(records, "midfielder", "goals_per90")) == [21]


# ----- the prediction test ----------------------------------------------------------------------

def test_later_seasons_never_leak_into_the_curve_used_for_prediction():
    records = _simulate(_truth, 1500, seed=4)
    before = ac.build_curve(records, "midfielder", "goals_per90", n_bootstrap=0, last_season_start=2022)
    # Rewrite the seasons after the training window; the curve built for the test must not notice.
    changed = [r if r.start_year <= 2022 else SeasonRecord(r.player_id, r.start_year, r.position, r.age,
                                                           r.minutes, r.goals + 50, r.assists) for r in records]
    after = ac.build_curve(changed, "midfielder", "goals_per90", n_bootstrap=0, last_season_start=2022)
    assert before.delta == after.delta and before.ages == after.ages
    # The pair 2021 to 2022 is the last one allowed, and the pair 2022 to 2023 is not.
    assert max(p.second.start_year for p in ac.consecutive_pairs(records) if p.second.start_year <= 2022) == 2022


def test_with_a_real_age_effect_the_curve_beats_the_same_as_last_season_baseline():
    # A steep rise for young players: carrying this season forward is wrong by about the rise.
    def steep(age):
        return 0.08 * min(age - 18, 6)
    records = _simulate(steep, 2500, seed=5)
    results, _ = ac.evaluate_prediction(records, n_bootstrap=100, seed=5)
    row = next(r for r in results if r.measure == "goals_per90")
    assert row.mae_curve < row.mae_same
    assert row.curve_minus_same[1] < 0      # the whole 80% interval is below zero
    assert row.n > 500 and row.players <= row.n


def test_with_no_age_effect_the_curve_is_not_reported_as_better():
    records = _simulate(lambda age: 0.0, 2500, seed=6)
    results, _ = ac.evaluate_prediction(records, n_bootstrap=100, seed=6)
    row = next(r for r in results if r.measure == "goals_per90")
    assert abs(row.mae_curve - row.mae_same) < 0.005   # nothing to learn from age, so nothing gained


def test_all_three_predictions_are_scored_on_the_same_rows():
    records = _simulate(_truth, 1500, seed=8)
    results, curves = ac.evaluate_prediction(records, n_bootstrap=20, seed=8)
    for row in results:
        assert row.n > 0 and row.players <= row.n
        assert all(np.isfinite([row.mae_curve, row.mae_same, row.mae_group]))
    assert ("midfielder", "goals_per90") in curves and ("midfielder", "minutes_share") in curves
    assert ("goalkeeper", "goals_per90") not in curves


def test_a_prediction_with_no_curve_and_no_players_returns_nothing():
    assert ac.evaluate_prediction([], n_bootstrap=5) == ([], {})


# ----- the cache loader -------------------------------------------------------------------------

def _make_cache(folder: Path):
    seasons = {1625: "2018/19", 2012: "2019/20", 2270: "2019/20"}   # 2270 is Liga MX
    manifest = {"seasons": {str(i): {"season_id": i, "league": "x", "label": label, "files": {}}
                            for i, label in seasons.items()}}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for season_id in seasons:
        (folder / str(season_id)).mkdir()
        rows = [_row(1), _row(2, position="Coach"), _row(3, birthday=0)]
        (folder / str(season_id) / "players.json").write_text(json.dumps({"data": rows}), encoding="utf-8")


def test_the_loader_reads_premier_league_seasons_only_and_reports_what_it_left_out(tmp_path):
    _make_cache(tmp_path)
    records, report = ac.load_records(tmp_path)
    assert sorted({r.start_year for r in records}) == [2018, 2019]          # Liga MX (2270) is never read
    assert [s["season_id"] for s in report.seasons] == [1625, 2012]
    assert report.rows_read == 6 and report.used == 2
    assert report.left_out["not a player (coach)"] == 2 and report.left_out["no birthday"] == 2


def test_the_loader_refuses_a_cache_inside_the_repository():
    inside = Path(ac.__file__).resolve().parents[2] / "some-cache"
    with pytest.raises(SystemExit):
        ac.load_records(inside)


# ----- the figure -------------------------------------------------------------------------------

def test_the_figure_is_valid_svg_with_a_panel_per_position_and_measure_and_no_goalkeeper_goals():
    import xml.etree.ElementTree as ET

    records = []
    for i, position in enumerate(ac.POSITIONS):
        # Player ids must differ between positions, or one player's seasons would overwrite another's.
        records += [SeasonRecord(r.player_id + 10_000 * i, r.start_year, r.position, r.age, r.minutes, r.goals,
                                 r.assists) for r in _simulate(_truth, 400, seed=9, position=position)]
    svg = figure.render(ac.all_curves(records, n_bootstrap=20, seed=9))
    ET.fromstring(svg)                       # well formed
    assert svg.count("<polygon") == 1 + 3 * 3   # the goalkeeper minutes panel and 9 outfield panels
    assert "\u2014" not in svg


def test_a_panel_with_no_age_of_enough_pairs_says_so_instead_of_drawing_nothing():
    curves = {(p, m): (None, {}) for p in ac.POSITIONS for m in ac.measures_for(p)}
    svg = figure.render(curves)
    assert svg.count("no age has 30 pairs") == 10
