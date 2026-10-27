"""The pro tier analyses (ml/pro): breakouts, finishing against xG, trends, and their evaluation.

The rules each analysis promises a scout, checked on small hand-made seasons, and the evaluation
checked on the tuning seeds only, so a change that quietly weakens the detector fails here
before it moves a number in ml/README.md.
"""

from __future__ import annotations

from datetime import date

import pytest

from ml.pro import breakout, sustainability, trends
from ml.pro import evaluate as pro_eval
from ml.pro.seasons import SeasonRow, consecutive

END_1, END_2 = date(2025, 5, 31), date(2026, 5, 31)


def _row(pid, end, *, club="c", minutes=2700, npxg=4.0, xa=2.0, goals=4, pens=0, age=21.0, **extra):
    metrics = {"minutes_played": minutes, "npxg": npxg, "xa": xa, "goals": goals, "penalty_goals": pens,
               "tackles": 40, "passes_attempted": 1000, "passes_completed": 800, "duels": 100,
               "duels_won": 50, "key_passes": 10, "dribbles_completed": 10, "interceptions": 20} | extra
    dob = date.fromordinal(end.toordinal() - int(age * 365.25))
    return SeasonRow(pid, f"{end.year - 1}/{str(end.year)[-2:]}", end, "League", club, "LW", dob, metrics)


def _team(club="c", players=11):
    return [_row(f"mate{i}", end, club=club, age=27) for i in range(players) for end in (END_1, END_2)]


def test_a_rise_in_share_of_the_teams_chances_is_flagged():
    rows = _team() + [_row("p", END_1, npxg=2.0, xa=1.0), _row("p", END_2, npxg=6.0, xa=3.0)]
    found = {a.player_id: a for a in breakout.detect(rows, END_1.year)}
    assert found["p"].flagged and found["p"].involvement_after > found["p"].involvement_before
    assert not found["mate0"].flagged


def test_a_whole_team_improving_is_not_a_breakout():
    """Every player's rate doubles with the team's: their share is unchanged."""
    rows = [_row(f"m{i}", END_1, age=21) for i in range(12)]
    rows += [_row(f"m{i}", END_2, age=21, npxg=8.0, xa=4.0) for i in range(12)]
    assert not [a for a in breakout.detect(rows, END_1.year) if a.flagged]


def test_breakouts_are_only_judged_in_the_age_window_and_with_minutes_both_seasons():
    rows = _team()
    rows += [_row("old", END_1, npxg=2.0, xa=1.0, age=29), _row("old", END_2, npxg=6.0, xa=3.0, age=29)]
    rows += [_row("bench", END_1, minutes=100), _row("bench", END_2, npxg=6.0, xa=3.0)]
    found = {a.player_id: a for a in breakout.detect(rows, END_1.year)}
    assert found["old"].score is None and "age window" in found["old"].reason
    assert found["bench"].score is None and "season before" in found["bench"].reason
    assert found["old"].flagged is False and found["bench"].flagged is False
    assert breakout.detect(rows, END_1.year, age_window=False)[0].score is not None


def test_a_season_without_the_team_on_record_is_not_scored():
    rows = [_row("abroad", END_1, club="x"), _row("abroad", END_2, club="x", npxg=9.0)]
    (only,) = breakout.detect(rows, END_1.year)
    assert only.score is None and "team is not on record" in only.reason


def test_the_first_season_covered_has_nothing_before_it():
    rows = [_row("p", END_1), _row("p", END_2)]
    assert [this.season for _, this in consecutive(rows, END_1.year)] == ["2025/26"]
    assert consecutive(rows, END_2.year) == []


@pytest.mark.parametrize(("k", "mean", "expected"), [(0, 1.0, 0.3679), (2, 1.0, 0.9197), (10, 8.0, 0.8159)])
def test_poisson_cdf(k, mean, expected):
    assert sustainability.poisson_cdf(k, mean) == pytest.approx(expected, abs=1e-4)


def test_finishing_verdicts():
    assert sustainability.judge(17, 8.0).verdict == "above"
    assert sustainability.judge(10, 8.0).verdict == "in line"
    assert sustainability.judge(2, 8.0).verdict == "below"
    assert sustainability.judge(5, 1.5).verdict == "too few chances"
    f = sustainability.judge(8, 8.0)
    assert (f.low, f.high) == (5, 12)


def test_penalties_are_left_out_of_finishing():
    row = _row("p", END_2, npxg=8.0, goals=17, pens=7)
    assert sustainability.season(row).np_goals == 10 and sustainability.season(row).verdict == "in line"


def test_pooling_seasons_narrows_the_range():
    one = sustainability.judge(12, 8.0)
    three = sustainability.career([_row("p", e, npxg=8.0, goals=12) for e in (END_1, END_2, date(2027, 5, 31))])
    assert one.verdict == "in line" and three.verdict == "above" and three.seasons == 3


def test_trends_need_enough_minutes_in_both_seasons():
    rows = [_row("p", END_1, minutes=2000), _row("p", END_2, minutes=2500)]
    (trend,) = trends.player_trends(rows, END_1.year)
    tackles = next(c for c in trend.changes if c.key == "tackles")
    assert (tackles.before, tackles.after, tackles.unit) == (1.8, 1.44, "per 90")
    passes = next(c for c in trend.changes if c.key == "pass_completion")
    assert (passes.before, passes.unit) == (80.0, "%")
    assert trends.player_trends([_row("p", END_1, minutes=600), _row("p", END_2)], END_1.year) == []


def test_on_the_tuning_seeds_v1_beats_both_comparisons():
    """The tuning seeds only: the reporting seeds' numbers live in ml/README.md and are never
    used to choose anything."""
    data = [pro_eval.league_data(seed) for seed in (101, 202, 303)]
    tp = fp = fn = 0
    for d in data:
        s = pro_eval.score_breakouts(d)
        tp, fp, fn = tp + s.tp, fp + s.fp, fn + s.fn
    f1 = 2 * tp / (2 * tp + fp + fn)
    per90 = [pro_eval.score_per90(d) for d in data]
    minutes = [pro_eval.score_minutes_only(d, 0.25) for d in data]

    def pooled(scores):
        a, b, c = (sum(getattr(s, k) for s in scores) for k in ("tp", "fp", "fn"))
        return 2 * a / (2 * a + b + c)

    assert f1 == pytest.approx(0.833, abs=0.001)
    assert f1 > pooled(per90) > pooled(minutes)


def test_on_the_tuning_seeds_xg_predicts_next_season_better_than_goals():
    report = pro_eval.score_finishing(pro_eval.league_data(101))
    assert report.mae["npxG per 90"] < report.mae["goals per 90"]
