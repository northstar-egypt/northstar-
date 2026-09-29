"""Tests for the challenger models (ml/challengers).

The XGBoost forecaster trains itself on whatever snapshot it is handed, which is exactly the
kind of model that can quietly learn from the future. So the no-lookahead test that guards the
v1 forecasters is run on it too: rewrite everything after an origin, and the forecasts made at
that origin must not move.

The isolation forest must never flag a player in the late-bloomer direction (small and still
growing), because calling a late bloomer a fraud is the worst mistake this platform can make.

Both skip cleanly when scikit-learn or xgboost is not installed, as the harness does.
"""

from __future__ import annotations

import pytest

pytest.importorskip("xgboost")
pytest.importorskip("sklearn")

from ml.challengers import isolation, xgb_forecast  # noqa: E402
from ml.detectors.features import FeatureSet  # noqa: E402
from ml.forecasting import walk_forward  # noqa: E402
from ml.forecasting.models import FORECASTERS, PlayerHistory, Snapshot  # noqa: E402
from ml.tests.test_forecasting import START, linear_population  # noqa: E402

WITH_XGBOOST = {**FORECASTERS, **xgb_forecast.FORECASTERS}


def test_xgboost_cannot_see_past_the_origin():
    """The same test the v1 forecasters pass, with the challenger included."""
    histories = linear_population()
    origins, cases = walk_forward.build_cases(histories, WITH_XGBOOST)
    origin = origins[len(origins) // 2]

    rewritten = {
        pid: PlayerHistory(
            h.player_id,
            h.sex,
            h.dob,
            [(when, cm if when <= origin else cm + 50.0) for when, cm in h.heights],
        )
        for pid, h in histories.items()
    }
    _, rewritten_cases = walk_forward.build_cases(rewritten, WITH_XGBOOST)

    def at_origin(case_list):
        return {
            (c.player_id, c.target): c.predictions[xgb_forecast.NAME]
            for c in case_list
            if c.origin == origin
        }

    before, after = at_origin(cases), at_origin(rewritten_cases)
    assert before and any(v is not None for v in before.values()), "nothing was forecast"
    assert before == after


def test_xgboost_learns_a_steady_growth_rate():
    """Children growing exactly 6 cm a year: a year ahead should land close to +6 cm."""
    from datetime import timedelta

    histories = linear_population()
    origin = START + timedelta(days=2 * 365)
    visible = {
        pid: PlayerHistory(h.player_id, h.sex, h.dob, [r for r in h.heights if r[0] <= origin])
        for pid, h in histories.items()
    }
    snapshot = Snapshot(origin, visible)
    history = visible["p0"]
    target = history.heights[-1][0] + timedelta(days=365)
    forecast = xgb_forecast.xgboost_forecast(snapshot, history, target)
    assert forecast is not None
    assert forecast - history.heights[-1][1] == pytest.approx(6.0, abs=0.75)


def test_xgboost_declines_rather_than_guessing_with_too_little_data():
    histories = dict(list(linear_population(n=2).items()))
    snapshot = Snapshot(START, {k: PlayerHistory(v.player_id, v.sex, v.dob, v.heights[:3]) for k, v in histories.items()})
    history = snapshot.players["p0"]
    assert xgb_forecast.xgboost_forecast(snapshot, history, START) is None


@pytest.fixture(scope="module")
def small_dataset(tmp_path_factory):
    from data.pipelines.synthetic.config import GeneratorConfig
    from data.pipelines.synthetic.dataset import build_dataset
    from data.pipelines.synthetic.ground_truth import write as write_ground_truth
    from data.pipelines.synthetic.writer import export_json

    out_dir = tmp_path_factory.mktemp("dataset")
    dataset = build_dataset(GeneratorConfig(seed=4242))
    write_ground_truth(dataset.ground_truth, out_dir / "ground_truth.json")
    export_json(dataset, out_dir)
    return out_dir


def test_the_forest_never_flags_the_late_bloomer_direction(small_dataset):
    features = FeatureSet(small_dataset)
    flagged = isolation.detect_age_misrepresentation(features)
    assert flagged, "the forest flagged nobody, so the test proves nothing"
    for pid in flagged:
        assert features.players[pid].maturity_mismatch > 0


def test_the_forest_is_deterministic(small_dataset):
    features = FeatureSet(small_dataset)
    assert isolation.detect_age_misrepresentation(features) == isolation.detect_age_misrepresentation(
        features
    )


def test_the_harness_scores_the_forest_on_the_same_cases_as_the_rule(small_dataset):
    from ml.evaluation.harness import evaluate

    report = evaluate(small_dataset)
    rule = report.subtypes["fraud, age: rule"]
    forest = report.subtypes["fraud, age: isolation forest"]
    assert rule.support == forest.support
    assert rule.population == forest.population
    assert any(a.detector == "fraud, age: isolation forest" for a in report.relative_age)


def test_the_api_never_needs_the_challengers():
    """The profile forecast runs the v1 model only; importing it must not pull in xgboost."""
    import pathlib

    source = pathlib.Path(__file__).resolve().parents[2] / "apps" / "api" / "app"
    for path in source.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "ml.challengers" not in text and "xgboost" not in text, path
