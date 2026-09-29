"""Tests for the relative age audit.

Two kinds of test. The arithmetic ones pin the chi-square and the quarter mapping, because a
wrong p-value here would turn a biased detector into a clean bill of health and nothing else
would notice. The end-to-end ones check the audit is actually wired into both reports.

The audit's power on real-shaped data is shown by the biased control in the harness itself
(`baselines.shortest_for_birth_year`), pooled over 20 seeds. That is too slow for this suite,
so it is recorded in ml/README.md instead, and here a planted bias in plain counts stands in.
"""

from __future__ import annotations

import json
import math
from datetime import date

import pytest

from ml.evaluation import fairness
from ml.evaluation.metrics import Score


@pytest.mark.parametrize(
    ("dob", "quarter"),
    [
        (date(2012, 1, 1), "Q1"),
        (date(2012, 3, 31), "Q1"),
        (date(2012, 4, 1), "Q2"),
        (date(2012, 9, 30), "Q3"),
        (date(2012, 10, 1), "Q4"),
        (date(2012, 12, 31), "Q4"),
        ("2012-07-15", "Q3"),
        ("2012-11-02T00:00:00", "Q4"),
        (None, None),
    ],
)
def test_birth_quarter_follows_the_calendar_year(dob, quarter):
    assert fairness.birth_quarter(dob) == quarter


def test_players_without_a_date_of_birth_belong_to_no_quarter():
    players = [
        {"id": "a", "date_of_birth": "2012-02-01"},
        {"id": "b", "date_of_birth": None},
        {"id": "c"},
    ]
    assert fairness.quarters_of(players) == {"a": "Q1"}


@pytest.mark.parametrize(
    ("statistic", "p"),
    # Textbook critical values for 3 degrees of freedom.
    [(0.0, 1.0), (0.584, 0.90), (2.366, 0.50), (7.815, 0.05), (11.345, 0.01), (16.266, 0.001)],
)
def test_chi_square_tail_matches_the_tables(statistic, p):
    assert fairness.chi_square_3df_p(statistic) == pytest.approx(p, abs=5e-4)


def test_chi_square_matches_scipy_when_it_is_installed():
    stats = pytest.importorskip("scipy.stats")
    flagged, totals = [3, 9, 14, 21], [250, 260, 240, 255]
    statistic, p = fairness.chi_square_independence(flagged, totals)
    table = [flagged, [t - f for f, t in zip(flagged, totals)]]
    expected = stats.chi2_contingency(table, correction=False)
    assert statistic == pytest.approx(expected[0])
    assert p == pytest.approx(expected[1])


def test_equal_rates_give_no_signal():
    assert fairness.chi_square_independence([5, 5, 5, 5], [100, 100, 100, 100]) == (0.0, 1.0)


def test_nobody_flagged_or_everybody_flagged_is_not_a_difference():
    assert fairness.chi_square_independence([0, 0, 0, 0], [50, 50, 50, 50]) == (0.0, 1.0)
    assert fairness.chi_square_independence([50, 50, 50, 50], [50, 50, 50, 50]) == (0.0, 1.0)


def test_an_empty_quarter_gets_no_p_value_rather_than_a_wrong_one():
    statistic, p = fairness.chi_square_independence([1, 4, 2, 0], [50, 50, 50, 0])
    assert statistic > 0
    assert math.isnan(p)


def _audit_with(fp: list[int], tn: list[int]) -> fairness.QuarterAudit:
    audit = fairness.QuarterAudit(detector="planted")
    for quarter, f, t in zip(fairness.QUARTERS, fp, tn):
        audit.by_quarter[quarter] = Score(detector="planted", tp=0, fp=f, fn=0, tn=t)
    return audit


def test_a_planted_relative_age_bias_is_caught():
    """Four times the false flags in Q4 as in Q1, at a realistic pooled size."""
    audit = _audit_with(fp=[5, 9, 14, 20], tn=[995, 991, 986, 980])
    statistic, p = audit.false_positive_test
    assert p < fairness.SIGNIFICANCE
    assert "differs by quarter" in fairness.render([audit], "t")


def test_no_bias_is_not_reported_as_one():
    audit = _audit_with(fp=[10, 11, 9, 10], tn=[990, 989, 991, 990])
    assert audit.false_positive_test[1] > 0.5
    assert "no detectable difference" in fairness.render([audit], "t")


def test_the_audit_splits_the_population_and_nothing_else():
    quarters = {"a": "Q1", "b": "Q1", "c": "Q2", "d": "Q4", "e": "Q4"}
    population = {"a", "b", "c", "d", "e", "no-dob"}
    audit = fairness.audit("x", predicted={"a", "d", "no-dob"}, truth={"a", "e"},
                           population=population, quarters=quarters)

    q1, q2, q3, q4 = (audit.by_quarter[q] for q in fairness.QUARTERS)
    assert (q1.tp, q1.fp, q1.fn, q1.tn) == (1, 0, 0, 1)
    assert (q2.tp, q2.fp, q2.fn, q2.tn) == (0, 0, 0, 1)
    assert q3.population == 0
    assert (q4.tp, q4.fp, q4.fn, q4.tn) == (0, 1, 1, 0)
    # The player with no date of birth is in no quarter, so the quarters sum to one less.
    assert sum(s.population for s in audit.by_quarter.values()) == len(population) - 1


def test_pooling_adds_counts_rather_than_averaging_rates():
    a = _audit_with(fp=[1, 0, 0, 0], tn=[9, 10, 10, 10])
    b = _audit_with(fp=[0, 0, 0, 3], tn=[90, 90, 90, 87])
    pooled = fairness.pool([a, b])
    assert pooled.by_quarter["Q1"].fp == 1 and pooled.by_quarter["Q1"].tn == 99
    assert pooled.by_quarter["Q4"].fp == 3 and pooled.by_quarter["Q4"].tn == 97


def test_json_output_is_strict_json_even_without_a_p_value():
    audit = _audit_with(fp=[1, 2, 0, 0], tn=[10, 10, 10, 0])
    payload = json.dumps(audit.as_dict(), allow_nan=False)
    assert json.loads(payload)["false_positive_p_value"] is None
    assert "not tested" in fairness.render([audit], "t")


# ---------------------------------------------------------------------------
# Wired into both reports
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def small_dataset(tmp_path_factory):
    from data.pipelines.synthetic.config import GeneratorConfig
    from data.pipelines.synthetic.dataset import build_dataset
    from data.pipelines.synthetic.ground_truth import write as write_ground_truth
    from data.pipelines.synthetic.writer import export_json

    out_dir = tmp_path_factory.mktemp("dataset")
    dataset = build_dataset(GeneratorConfig(seed=4242).scaled(120))
    write_ground_truth(dataset.ground_truth, out_dir / "ground_truth.json")
    export_json(dataset, out_dir)
    return out_dir


def test_the_detector_report_carries_the_audit_and_its_biased_control(small_dataset):
    from ml.evaluation.harness import evaluate, render

    report = evaluate(small_dataset)
    names = [a.detector for a in report.relative_age]
    assert "late_bloomer v1" in names
    assert "fraud: age misrepresentation" in names
    assert "duplicate v1" in names
    assert "control: birth-year cohort" in names
    for audit in report.relative_age:
        assert set(audit.by_quarter) == set(fairness.QUARTERS)
    assert "Relative age audit" in render(report)
    json.dumps(report.as_dict(), allow_nan=False)


def test_the_headline_scores_are_untouched_by_the_audit(small_dataset):
    """The audit reads the detectors' output; it must not change what they are scored on."""
    from ml.evaluation.harness import evaluate

    report = evaluate(small_dataset)
    late = next(a for a in report.relative_age if a.detector == "late_bloomer v1")
    headline = report.headline["late_bloomer"]
    assert sum(s.tp for s in late.by_quarter.values()) == headline.tp
    assert sum(s.fp for s in late.by_quarter.values()) == headline.fp


def test_the_forecast_report_is_split_by_birth_quarter(small_dataset):
    from ml.forecasting.walk_forward import HEADLINE, evaluate

    report = evaluate(small_dataset)
    groups = [g for g in report.groups if "born Q" in g]
    assert len(groups) == 4
    total = sum(report.groups[g][0].n + report.groups[g][0].missing for g in groups)
    headline = report.groups[HEADLINE][0]
    assert total == headline.n + headline.missing
