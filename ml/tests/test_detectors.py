"""Tests for the three detectors and the end-to-end harness.

The unit tests pin the pieces a reviewer cannot check by eye, mainly the Arabic
name normalisation and the arithmetic rules. The end-to-end test generates a
small dataset and asserts that each detector beats the trivial baseline for its
class, which is the property that actually matters and the one most likely to
break silently when someone tunes a threshold.

Numbers are asserted as floors, not as exact values. A test that pins F1 to three
decimals fails on every harmless change and teaches everyone to update the
expected value without reading it.
"""

from __future__ import annotations

from datetime import date

import pytest

from ml.detectors import baselines, duplicate, fraud
from ml.detectors.features import FeatureSet
from ml.evaluation.harness import evaluate
from ml.evaluation.metrics import score_ids

# ---------------------------------------------------------------------------
# Arabic name normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a,b",
    [
        ("أحمد محمد", "احمد محمد"),  # hamza on alef
        ("إبراهيم علي", "ابراهيم علي"),  # hamza under alef
        ("فاطمة حسن", "فاطمه حسن"),  # teh marbuta to heh
        ("يحيى سعيد", "يحيي سعيد"),  # alef maqsura and yeh
        ("مؤمن عادل", "مومن عادل"),  # hamza on waw
        ("أحمد  محمد", "أحمد محمد"),  # the doubled space a second typing leaves
    ],
)
def test_orthographic_variants_normalise_to_the_same_string(a, b):
    assert duplicate.normalise_name(a) == duplicate.normalise_name(b)


def test_different_names_do_not_normalise_together():
    assert duplicate.normalise_name("أحمد محمد") != duplicate.normalise_name("خالد محمد")


def test_dropped_name_part_still_matches_by_containment():
    """Egyptian names carry the father's and grandfather's names; one clerk types fewer."""
    full = duplicate.name_tokens("احمد محمد ابراهيم علي")
    short = duplicate.name_tokens("احمد ابراهيم علي")
    assert duplicate.token_containment(full, short) == 1.0


def test_containment_is_not_fooled_by_a_single_shared_part():
    a = duplicate.name_tokens("احمد محمد")
    b = duplicate.name_tokens("احمد خالد")
    assert duplicate.token_containment(a, b) == 0.5


# ---------------------------------------------------------------------------
# Date of birth relations
# ---------------------------------------------------------------------------


def test_dob_relations():
    assert duplicate.dob_relation(date(2010, 3, 7), date(2010, 3, 7), 7) == "exact"
    assert duplicate.dob_relation(date(2010, 3, 7), date(2010, 3, 10), 7) == "within_days"
    assert (
        duplicate.dob_relation(date(2010, 3, 7), date(2010, 7, 3), 7)
        == "day_month_transposed"
    )
    assert duplicate.dob_relation(date(2010, 3, 7), date(2011, 9, 1), 7) is None
    assert duplicate.dob_relation(None, date(2010, 3, 7), 7) is None


def test_transposition_that_would_be_an_invalid_date_is_not_a_crash():
    """Day 25 cannot become a month. The check has to survive that, not raise."""
    assert duplicate.dob_relation(date(2010, 3, 25), date(2010, 5, 1), 7) is None


# ---------------------------------------------------------------------------
# Arithmetic fraud rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "metrics",
    [
        {"goals": 3, "shots": 1},
        {"shots_on_target": 5, "shots": 2},
        {"passes_completed": 40, "passes_attempted": 12},
        {"distance_km": 18.2},
        {"minutes_played": 0, "goals": 2},
    ],
)
def test_impossible_rows_are_caught(metrics):
    pf = _fake_player_with_entries([metrics])
    assert fraud.impossible_rows(pf)


@pytest.mark.parametrize(
    "metrics",
    [
        {"goals": 1, "shots": 4, "shots_on_target": 2},
        {"passes_completed": 30, "passes_attempted": 41},
        {"distance_km": 11.4},
        {"minutes_played": 0, "goals": 0},
        {},
    ],
)
def test_ordinary_rows_are_not_caught(metrics):
    pf = _fake_player_with_entries([metrics])
    assert not fraud.impossible_rows(pf)


def test_metrics_that_are_not_a_dict_do_not_crash_the_rule():
    pf = _fake_player_with_entries([None, "nonsense", {"goals": 2, "shots": 0}])
    assert len(fraud.impossible_rows(pf)) == 1


def _fake_player_with_entries(metric_dicts):
    from ml.detectors.features import PlayerFeatures

    pf = PlayerFeatures(player_id="p", player={"id": "p"})
    pf.performance = [
        {"id": f"e{i}", "metrics": m} for i, m in enumerate(metric_dicts)
    ]
    return pf


# ---------------------------------------------------------------------------
# End to end, against a generated dataset
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def small_dataset(tmp_path_factory):
    """A scaled-down dataset, generated once for the module.

    Smaller than the committed default so the suite stays quick. Planted case
    counts scale with the population, so the detectors still have something to
    find.
    """
    from data.pipelines.synthetic.config import GeneratorConfig
    from data.pipelines.synthetic.dataset import build_dataset
    from data.pipelines.synthetic.ground_truth import write as write_ground_truth
    from data.pipelines.synthetic.writer import export_json

    out_dir = tmp_path_factory.mktemp("dataset")
    dataset = build_dataset(GeneratorConfig(seed=4242).scaled(120))
    write_ground_truth(dataset.ground_truth, out_dir / "ground_truth.json")
    export_json(dataset, out_dir)
    return out_dir


def test_harness_runs_and_reports_every_detector(small_dataset):
    report = evaluate(small_dataset)
    assert set(report.headline) == {"late_bloomer", "fraud", "duplicate"}
    assert report.population > 0
    for score in report.headline.values():
        assert score.population == report.population


def test_every_detector_beats_random_at_the_same_prevalence(small_dataset):
    """The floor. A detector that cannot clear this is not detecting anything."""
    report = evaluate(small_dataset)
    features = FeatureSet(small_dataset)

    for name, score in report.headline.items():
        chance = score_ids(
            name,
            baselines.random_at_prevalence(features, score.support, seed=1),
            # Reconstruct the truth set from the score itself.
            set(score.false_negatives) | _true_positives(score, report, name),
            features.population,
        )
        assert score.f1 > chance.f1, f"{name} did not beat random"


def _true_positives(score, report, name) -> set[str]:
    """The answer key minus the misses, recovered without reloading the file."""
    from ml.evaluation.harness import load_ground_truth

    gt = load_ground_truth(report.data_dir)
    return set(gt["labels"][name])


def test_duplicate_detector_beats_exact_name_matching(small_dataset):
    """The whole point of normalising Arabic spelling."""
    report = evaluate(small_dataset)
    section = next(s for s in report.sections if s.title == "Duplicate identity")
    exact = next(s for s in section.scores if "exact name match" in s.detector)
    assert report.headline["duplicate"].recall > exact.recall


def test_duplicate_detector_does_not_read_the_merge_pointer(small_dataset):
    """`merged_into` is the record of a merge a human already did, not a signal.

    Reading it would score about half the answer key while detecting nothing. This
    asserts the detector finds the unresolved clusters too, which is the half no
    pointer exists for.
    """
    report = evaluate(small_dataset)
    section = next(s for s in report.sections if s.title == "Duplicate identity")
    unresolved = next(s for s in section.scores if "unresolved" in s.detector)
    assert unresolved.tp > 0
    assert unresolved.recall > 0.5


def test_impossible_metric_rule_finds_the_injected_rows_exactly(small_dataset):
    """Row level, against the ids the generator recorded when it injected them.

    The generator guarantees every other row is consistent by construction, so
    anything extra this flags is a bug in the rule rather than a near miss.
    """
    report = evaluate(small_dataset)
    section = next(
        s for s in report.sections if s.title == "Fraud, scored per performance row"
    )
    rows = section.scores[0]
    assert rows.fp == 0
    assert rows.fn == 0
