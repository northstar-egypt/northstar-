"""Tests for the scoring primitives.

These matter more than the usual unit test. Everything the detector deliverable
claims rests on these four counts being right, and a scoring bug does not crash,
it just reports a better number than the truth.
"""

from __future__ import annotations

import math

import pytest

from ml.evaluation.metrics import Score, ScoreSet, score_ids, wilson_interval


def test_counts_and_rates_on_a_worked_example():
    population = {"a", "b", "c", "d", "e", "f", "g", "h", "i", "j"}
    truth = {"a", "b", "c", "d"}
    predicted = {"a", "b", "e"}

    s = score_ids("t", predicted, truth, population)

    assert (s.tp, s.fp, s.fn, s.tn) == (2, 1, 2, 5)
    assert s.tp + s.fp + s.fn + s.tn == len(population)
    assert s.support == 4
    assert s.predicted == 3
    assert s.precision == pytest.approx(2 / 3)
    assert s.recall == pytest.approx(0.5)
    assert s.f1 == pytest.approx(2 * (2 / 3) * 0.5 / ((2 / 3) + 0.5))
    assert s.prevalence == pytest.approx(0.4)
    assert s.false_negatives == ("c", "d")
    assert s.false_positives == ("e",)


def test_ids_outside_the_population_are_dropped_not_counted():
    """A detector inventing ids is a bug, and must not quietly become a false positive."""
    s = score_ids("t", {"a", "ghost"}, {"a", "b"}, {"a", "b", "c"})
    assert (s.tp, s.fp, s.fn, s.tn) == (1, 0, 1, 1)
    assert s.population == 3


def test_perfect_and_empty_predictions():
    population = {"a", "b", "c", "d"}
    truth = {"a", "b"}

    perfect = score_ids("t", truth, truth, population)
    assert (perfect.precision, perfect.recall, perfect.f1) == (1.0, 1.0, 1.0)

    empty = score_ids("t", set(), truth, population)
    assert empty.predicted == 0
    # Undefined precision is reported as 0.0. Paired with predicted == 0 in the
    # table, which is what stops it reading as a bad detector rather than an
    # absent one.
    assert empty.precision == 0.0
    assert empty.recall == 0.0
    assert empty.f1 == 0.0


def test_flagging_everything_scores_precision_equal_to_prevalence():
    """The baseline that exists to make a bare recall of 1.0 look as cheap as it is."""
    population = {str(i) for i in range(100)}
    truth = {str(i) for i in range(7)}
    s = score_ids("all", population, truth, population)
    assert s.recall == 1.0
    assert s.precision == pytest.approx(0.07)
    assert s.precision == pytest.approx(s.prevalence)


def test_empty_population_does_not_divide_by_zero():
    s = score_ids("t", set(), set(), set())
    assert (s.precision, s.recall, s.f1, s.prevalence) == (0.0, 0.0, 0.0, 0.0)


@pytest.mark.parametrize(
    "successes,total",
    [(0, 10), (10, 10), (1, 1), (7, 14), (3, 212)],
)
def test_wilson_interval_stays_inside_zero_to_one(successes, total):
    """The reason for Wilson over the normal approximation.

    The normal interval happily returns bounds below 0 or above 1 at exactly the
    proportions this project reports: 14 positives, and rates near the ends.
    """
    lo, hi = wilson_interval(successes, total)
    assert 0.0 <= lo <= hi <= 1.0
    assert lo <= successes / total <= hi


def test_wilson_interval_narrows_as_the_sample_grows():
    narrow = wilson_interval(50, 100)
    wide = wilson_interval(5, 10)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_wilson_interval_of_an_empty_sample():
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_score_set_round_trips_to_dict():
    section = ScoreSet("title")
    section.add(score_ids("d", {"a"}, {"a", "b"}, {"a", "b", "c"}))
    payload = section.as_dict()
    assert payload["title"] == "title"
    assert payload["scores"][0]["tp"] == 1
    assert payload["scores"][0]["recall"] == 0.5


def test_f1_matches_the_textbook_definition():
    """Cross-check against the harmonic mean computed independently."""
    s = Score(detector="t", tp=6, fp=3, fn=4, tn=87)
    precision = 6 / 9
    recall = 6 / 10
    expected = 2 / (1 / precision + 1 / recall)
    assert s.f1 == pytest.approx(expected)
    assert not math.isnan(s.f1)


def test_f1_matches_sklearn_when_it_is_installed():
    """Belt and braces against the one number the project is graded on.

    Skipped rather than required, because `ml/detectors` is deliberately
    standard-library only and the harness has to run in an environment that has
    nothing else installed.
    """
    sklearn_metrics = pytest.importorskip("sklearn.metrics")

    population = [str(i) for i in range(50)]
    truth = {"1", "2", "3", "4", "5", "6"}
    predicted = {"1", "2", "3", "40", "41"}

    s = score_ids("t", predicted, truth, population)
    y_true = [1 if p in truth else 0 for p in population]
    y_pred = [1 if p in predicted else 0 for p in population]

    precision, recall, f1, _ = sklearn_metrics.precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0
    )
    assert s.precision == pytest.approx(precision)
    assert s.recall == pytest.approx(recall)
    assert s.f1 == pytest.approx(f1)
