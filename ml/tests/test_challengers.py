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


def test_the_api_takes_only_the_challenger_that_won():
    """XGBoost won and the profile runs it. The isolation forest did not, so the API must not
    import it, or scikit-learn, which the API image does not install."""
    import pathlib

    source = pathlib.Path(__file__).resolve().parents[2] / "apps" / "api" / "app"
    for path in source.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "isolation" not in text and "sklearn" not in text, path


def test_xgboost_trains_without_scikit_learn():
    """The API image has no scikit-learn. XGBoost's scikit-learn wrapper refuses to run
    without it, which once passed every test here and then failed in the container. Run in a
    fresh interpreter with scikit-learn made unimportable."""
    import pathlib
    import subprocess
    import sys

    script = (
        "import sys; sys.modules['sklearn'] = None\n"
        "from datetime import timedelta\n"
        "from ml.challengers import xgb_forecast\n"
        "from ml.forecasting.models import Snapshot\n"
        "from ml.tests.test_forecasting import START, linear_population\n"
        "snapshot = Snapshot(START + timedelta(days=730), linear_population())\n"
        "assert xgb_forecast.train(snapshot) is not None\n"
    )
    root = pathlib.Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=root, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_the_api_trains_the_same_model_the_evaluation_scores():
    """`train` + `predict`, which the API calls, give exactly what `xgboost_forecast`, which
    the evaluation calls, gives on the same snapshot."""
    from datetime import timedelta

    histories = linear_population()
    origin = START + timedelta(days=2 * 365)
    visible = {
        pid: PlayerHistory(h.player_id, h.sex, h.dob, [r for r in h.heights if r[0] <= origin])
        for pid, h in histories.items()
    }
    snapshot = Snapshot(origin, visible)
    model = xgb_forecast.train(snapshot)
    for history in list(visible.values())[:5]:
        target = origin + timedelta(days=182)
        assert xgb_forecast.predict(model, snapshot, history, target) == pytest.approx(
            xgb_forecast.xgboost_forecast(snapshot, history, target)
        )


# ---------------------------------------------------------------------------
# Growth-timing fit (tempo_fit). It lost to the v1 rule; these check it is the method it says
# it is, so the reported loss is the method's and not a bug's.
# ---------------------------------------------------------------------------


def _toy_curve():
    """A made-up median curve with a spurt at 12 to 15: cm by whole year, 8 to 22."""
    heights = [127, 132, 137, 142, 148, 155, 162, 168, 172, 174, 175, 175.5, 176, 176, 176]
    return list(zip(range(8, 23), heights))


def test_tempo_fit_finds_a_late_spurt_and_an_on_time_one():
    from ml.challengers import tempo_fit

    curve = _toy_curve()
    ages = [12.0, 12.5, 13.0, 13.5, 14.0, 14.5]
    on_time = [(a, tempo_fit._at(curve, a)) for a in ages]
    late = [(a, tempo_fit._at(curve, a - 1.5)) for a in ages]

    tau_on, size_on = tempo_fit.fit(on_time, curve, 0.04)
    tau_late, _ = tempo_fit.fit(late, curve, 0.04)
    assert abs(tau_on) < 0.15 and abs(size_on - 1) < 0.01
    # The prior pulls toward on time, so the estimate is shrunk, but it is clearly late.
    assert 1.0 <= tau_late <= 1.6
    assert tau_late >= tempo_fit.TAU_THRESHOLD


def test_tempo_fit_does_not_read_a_small_on_time_child_as_late():
    from ml.challengers import tempo_fit

    curve = _toy_curve()
    ages = [12.0, 12.5, 13.0, 13.5, 14.0, 14.5]
    small = [(a, 0.95 * tempo_fit._at(curve, a)) for a in ages]
    tau, size = tempo_fit.fit(small, curve, 0.04)
    assert tau < tempo_fit.TAU_THRESHOLD
    assert size < 1


def test_sitar_knot_heights_are_window_medians_and_none_when_too_sparse():
    from ml.challengers import sitar

    aligned = sorted([(12.0 + 0.1 * k, 150.0 + k) for k in range(7)] + [(18.0, 170.0)])
    heights = sitar._knot_heights(aligned, [12.3, 18.0])
    assert heights[0] == 153.0  # the median of the readings within half a year of 12.3
    assert heights[1] is None   # one reading near 18 is not enough to move a knot


def test_sitar_is_deterministic_and_only_flags_children_v1_would_consider(small_dataset):
    from ml.challengers import sitar, tempo_fit
    from ml.detectors.features import FeatureSet
    from ml.detectors.late_bloomer import LateBloomerParams

    features = FeatureSet(small_dataset)
    first, second = sitar.fitted_taus(features), sitar.fitted_taus(features)
    assert first == second
    params = LateBloomerParams()
    assert all(tempo_fit.eligible(features.players[pid], params) for pid in first)
    assert set(sitar.detect(features)) == {p for p, t in first.items() if t >= sitar.TAU_THRESHOLD}
