"""The pro scouting report (ml/pro/report.py) and its validity check (ml/pro/report_eval.py).

The rules on small hand-made leagues: who gets a report and who is told why not, the grade
cut-offs, a role graded only on the areas it needs, and evidence that carries its median.
Then the validity check on one league, so a change that breaks the link between the report and
true quality fails here before it moves a number in ml/README.md.
"""

from __future__ import annotations

from datetime import date

import pytest

from ml.pro import report as reports
from ml.pro.seasons import SeasonRow
from ml.sport_modules import registry

MODULE = registry()["football"]
END = date(2026, 5, 31)


def _row(pid, *, position="CB", minutes=2400, age=25.0, scale=1.0, club=None):
    """A season whose every rate scales with `scale`, so a higher scale ranks higher everywhere."""
    m = {
        "minutes_played": minutes, "npxg": 2.0 * scale, "shots": int(30 * scale), "xa": 1.5 * scale,
        "key_passes": int(20 * scale), "crosses": int(15 * scale), "dribbles_completed": int(20 * scale),
        "tackles": int(40 * scale), "interceptions": int(30 * scale), "clearances": int(50 * scale),
        "passes_attempted": int(1200 * scale), "passes_completed": int(1200 * scale * min(0.95, 0.6 + 0.1 * scale)),
        "duels": 200, "duels_won": int(min(200, 80 * scale)), "aerial_duels": 60,
        "aerial_duels_won": int(min(60, 24 * scale)),
    }
    dob = date.fromordinal(END.toordinal() - int(age * 365.25))
    return SeasonRow(pid, "2025/26", END, "Test League", club or f"club-{pid}", position, dob, m)


def _league(position="CB", n=12):
    return [_row(f"p{i}", position=position, scale=0.6 + 0.08 * i) for i in range(n)]


@pytest.mark.parametrize(("score", "letter"), [(90, "A"), (85, "A"), (84.9, "B"), (70, "B"), (50, "C"), (49, "D"), (None, None)])
def test_grade_cut_offs(score, letter):
    assert reports.grade(score) == letter


@pytest.mark.parametrize(
    ("n", "word"),
    [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"), (13, "13th"), (21, "21st"),
     (73, "73rd"), (72.6, "73rd")],
)
def test_ordinals_read_properly(n, word):
    assert reports.ordinal(n) == word


def test_sentences_keep_a_statistics_own_capitals():
    assert reports._in_a_sentence("xA per 90") == "xA per 90"
    assert reports._in_a_sentence("npxG per 90") == "npxG per 90"
    assert reports._in_a_sentence("Key passes per 90") == "key passes per 90"


def test_the_best_centre_back_is_shortlisted_and_the_worst_is_not_now():
    rows = _league()
    best, worst = reports.build(MODULE, rows, "p11"), reports.build(MODULE, rows, "p0")
    assert best.recommendation == "Shortlist" and best.level_grade == "A"
    assert worst.recommendation == "Not now" and worst.level_grade == "D"
    assert best.population == 11 and best.group == "centre_backs"


def test_a_role_is_graded_only_on_the_areas_it_needs():
    rep = reports.build(MODULE, _league(), "p6")
    graded = {a.key for a in rep.areas if a.graded}
    assert graded == set(MODULE.scouting_report.roles["centre_backs"])
    assert "goal_threat" not in graded


def test_evidence_carries_value_percentile_median_and_reliability():
    rep = reports.build(MODULE, _league(), "p11")
    assert rep.strengths and all(e.percentile >= reports.STRONG for e in rep.strengths)
    tackles = next(e for a in rep.areas for e in a.evidence if e.key == "tackles_per_90")
    assert tackles.unit == "per 90" and tackles.low_reliability is True and tackles.median > 0
    completion = next(e for a in rep.areas for e in a.evidence if e.key == "pass_completion")
    assert completion.unit == "%" and completion.value > 50


def test_confidence_follows_minutes():
    rows = _league() + [_row("short", minutes=900, scale=1.2)]
    assert reports.build(MODULE, rows, "p11").confidence == "high"
    assert reports.build(MODULE, rows, "short").confidence == "low"
    assert any("fuller season" in w for w in reports.build(MODULE, rows, "short").would_change)


@pytest.mark.parametrize(
    ("extra", "pid", "reason"),
    [
        (_row("kid", age=16.5), "kid", "adult players"),
        (_row("keeper", position="GK"), "keeper", "goalkeeping"),
        (_row("bench", minutes=200), "bench", "minutes"),
    ],
)
def test_who_gets_no_report_is_told_why(extra, pid, reason):
    with pytest.raises(reports.NoReport, match=reason):
        reports.build(MODULE, _league() + [extra], pid)


def test_too_few_players_to_compare_with_gives_no_report():
    with pytest.raises(reports.NoReport, match="Too few"):
        reports.build(MODULE, _league(n=5), "p2")


def test_on_one_league_the_level_tracks_true_quality_better_than_minutes():
    from ml.pro import report_eval

    result = report_eval.evaluate(101, MODULE)
    level = [v for v in result.by_group.values() if v is not None]
    minutes = [v for v in result.minutes_by_group.values() if v is not None]
    assert sum(level) / len(level) > sum(minutes) / len(minutes) + 0.1
    shortlisted, in_top = result.recommendations["Shortlist"]
    assert shortlisted and in_top / shortlisted > 0.5
