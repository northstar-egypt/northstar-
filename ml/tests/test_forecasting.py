"""Tests for the height forecasters and the walk-forward harness.

The test that matters most is the lookahead one. A walk-forward number is only worth
reporting if nothing after the origin can reach a forecast made at the origin, and that is
exactly the kind of leak that makes a model look brilliant and is invisible in the output.
So it is tested directly: rewrite everything after an origin and check that the forecasts
made at that origin do not move.

As in test_detectors.py, results are asserted as floors rather than pinned values.
"""

from __future__ import annotations

import ast
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from ml.evaluation.metrics import error_score
from ml.forecasting import models, walk_forward
from ml.forecasting.models import PlayerHistory, Snapshot

# ---------------------------------------------------------------------------
# A population whose future is known exactly
# ---------------------------------------------------------------------------

START = date(2020, 1, 1)


def linear_population(n: int = 40, rate: float = 6.0) -> dict[str, PlayerHistory]:
    """Children who all grow exactly `rate` cm a year, measured every 60 days for 3 years."""
    histories = {}
    for index in range(n):
        dob = date(2008 + index % 5, 1 + index % 12, 1)
        base = 140.0 + index % 7
        readings = []
        when = START
        while when <= START + timedelta(days=3 * 365):
            years = (when - START).days / models.DAYS_PER_YEAR
            readings.append((when, base + rate * years))
            when += timedelta(days=60)
        histories[f"p{index}"] = PlayerHistory(f"p{index}", "male", dob, readings)
    return histories


def truncated(histories: dict[str, PlayerHistory], origin: date) -> dict[str, PlayerHistory]:
    return {
        pid: PlayerHistory(h.player_id, h.sex, h.dob, [r for r in h.heights if r[0] <= origin])
        for pid, h in histories.items()
    }


def test_last_value_is_the_last_reading():
    history = linear_population()["p0"]
    snapshot = Snapshot(START, {"p0": history})
    assert models.last_value(snapshot, history, START) == history.heights[-1][1]


def test_cohort_velocity_learns_the_growth_rate_from_the_data():
    """Everyone grows 6 cm a year, so a year ahead should be about 6 cm taller."""
    origin = START + timedelta(days=2 * 365)
    visible = truncated(linear_population(), origin)
    snapshot = Snapshot(origin, visible)
    history = visible["p3"]
    target = history.heights[-1][0] + timedelta(days=365)
    forecast = models.cohort_velocity(snapshot, history, target)
    assert forecast == pytest.approx(history.heights[-1][1] + 6.0, abs=0.3)


def test_no_forecaster_needs_more_than_the_history_it_is_given():
    origin = START + timedelta(days=2 * 365)
    visible = truncated(linear_population(), origin)
    snapshot = Snapshot(origin, visible)
    for forecast in models.FORECASTERS.values():
        value = forecast(snapshot, visible["p1"], origin + timedelta(days=100))
        assert value is not None and math.isfinite(value)


def test_forecasters_decline_rather_than_guess_with_no_history():
    empty = PlayerHistory("x", "male", date(2010, 1, 1), [])
    snapshot = Snapshot(START, {"x": empty})
    assert models.last_value(snapshot, empty, START) is None
    assert models.cohort_velocity(snapshot, empty, START) is None


# ---------------------------------------------------------------------------
# Walk-forward integrity
# ---------------------------------------------------------------------------


def test_forecasts_at_an_origin_cannot_see_past_it():
    """Rewrite the future and the forecasts made before it must not change."""
    histories = linear_population()
    origins, cases = walk_forward.build_cases(histories)
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
    _, rewritten_cases = walk_forward.build_cases(rewritten)

    before = {(c.player_id, c.target): c.predictions for c in cases if c.origin == origin}
    after = {
        (c.player_id, c.target): c.predictions for c in rewritten_cases if c.origin == origin
    }
    assert before, "no cases at the chosen origin, so the test proves nothing"
    assert before == after


def test_every_case_is_forecast_from_before_its_target():
    _, cases = walk_forward.build_cases(linear_population())
    assert cases
    for case in cases:
        assert case.origin < case.target
        assert case.horizon_days <= walk_forward.MAX_HORIZON_DAYS


def test_uncertainty_band_is_calibrated_only_on_outcomes_already_measured():
    origin = START + timedelta(days=400)
    case = walk_forward.Case(
        player_id="p",
        origin=START,
        target=origin + timedelta(days=1),
        actual=150.0,
        stated_age=12.0,
        sex="male",
        predictions={walk_forward.INTERVAL_MODEL: 140.0},
    )
    assert walk_forward._interval_errors([case], origin) == {}
    later = origin + timedelta(days=1)
    assert walk_forward._interval_errors([case], later) != {}


def test_forecasting_never_imports_the_generator():
    """The generator's growth curve is the answer key. See the note in models.py."""
    package = Path(walk_forward.__file__).parent
    for source in package.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] != "data", source.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] != "data", source.name


# ---------------------------------------------------------------------------
# Error metrics
# ---------------------------------------------------------------------------


def test_error_score_arithmetic():
    pairs = [("a", 11.0, 10.0), ("a", 8.0, 10.0), ("b", 10.0, 10.0), ("b", None, 10.0)]
    score = error_score("m", pairs)
    assert score.n == 3
    assert score.missing == 1
    assert score.mae == pytest.approx(1.0)
    assert score.rmse == pytest.approx(math.sqrt(5 / 3))
    assert score.bias == pytest.approx(-1 / 3)
    low, high = score.mae_ci
    assert low <= score.mae <= high


# ---------------------------------------------------------------------------
# End to end on a generated dataset
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def small_dataset(tmp_path_factory):
    from data.pipelines.synthetic.config import GeneratorConfig
    from data.pipelines.synthetic.dataset import build_dataset
    from data.pipelines.synthetic.ground_truth import write as write_ground_truth
    from data.pipelines.synthetic.writer import export_json

    out_dir = tmp_path_factory.mktemp("forecast_dataset")
    dataset = build_dataset(GeneratorConfig(seed=4242).scaled(120))
    write_ground_truth(dataset.ground_truth, out_dir / "ground_truth.json")
    export_json(dataset, out_dir)
    return out_dir


def test_the_model_beats_both_baselines_on_growing_players(small_dataset):
    """The graded property: a model that cannot beat these is not done."""
    report = walk_forward.evaluate(small_dataset)
    scores = {s.forecaster: s for s in report.groups[walk_forward.HEADLINE]}
    model = scores["cohort velocity"].mae
    assert model < scores["baseline: last value"].mae
    assert model < scores["baseline: population average"].mae


def test_the_band_covers_roughly_what_it_claims(small_dataset):
    report = walk_forward.evaluate(small_dataset)
    assert report.interval_cases > 0
    coverage = report.interval_hits / report.interval_cases
    assert 0.65 <= coverage <= 0.95
