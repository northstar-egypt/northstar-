"""Tests for the late-bloomer figure (ml/figure_late_bloomer.py).

The figure is graded material, so what is tested is that it cannot show something false: the
player is the one the stated rule picks, the measured points are the measured readings, the
dashed line is the planted curve and ends at the planted adult height, and the rates in the
caption are the backtest's own.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

import pytest

from ml import figure_late_bloomer as fig
from ml.backtest import Decision, Rate


def _decision(pid, *, age, flagged=True, lb=True, sex="male"):
    return Decision(
        player_id=pid,
        cutoff=date(2024, 1, 1),
        sex=sex,
        stated_age=age,
        height_z=-1.5,
        readings=4,
        flagged=flagged,
        planted_late_bloomer=lb,
    )


def test_the_rule_picks_the_flagged_football_boy_closest_to_14():
    decisions = [
        _decision("a", age=12.1),
        _decision("b", age=14.4),
        _decision("c", age=13.9, flagged=False),  # closer, but not flagged
        _decision("d", age=14.0, lb=False),  # not a late bloomer
        _decision("e", age=14.0, sex="female"),  # football is boys only
        _decision("f", age=14.05),  # closest, but table tennis
    ]
    players = {d.player_id: {"primary_sport": "football"} for d in decisions}
    players["f"]["primary_sport"] = "table_tennis"
    assert fig.choose(decisions, players).player_id == "b"


def test_no_candidate_is_an_error_not_a_made_up_example():
    with pytest.raises(SystemExit):
        fig.choose([_decision("a", age=14.0, flagged=False)], {"a": {"primary_sport": "football"}})


@pytest.fixture(scope="module")
def example(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("figure") / str(fig.DEFAULT_SEED)
    fig._generate(fig.DEFAULT_SEED, out_dir, attrition=False, players=None)
    return fig.build_example(out_dir), out_dir


def test_the_points_are_the_measured_readings_and_the_curve_is_the_planted_one(example):
    import json

    from ml.detectors.features import FeatureSet

    ex, out_dir = example
    pf = FeatureSet(out_dir).players[ex.decision.player_id]
    assert [cm for _, cm in ex.readings] == [cm for _, cm in pf.heights]

    truth = json.loads((out_dir / "ground_truth.json").read_text(encoding="utf-8"))
    case = next(
        c for c in truth["cases"]["late_bloomers"] if c["player_id"] == ex.decision.player_id
    )
    assert ex.adult_height_cm == case["projected_adult_height_cm"]
    assert ex.decision.flagged and ex.decision.planted_late_bloomer
    # The dashed line starts at the last reading and runs until he has stopped growing.
    assert ex.planted_curve[0][0] == ex.readings[-1][0]
    assert abs(ex.planted_curve[-1][1] - ex.adult_height_cm) < 0.1


def test_the_svg_carries_the_backtest_rates_and_says_what_is_not_measured(example):
    ex, _ = example
    rates = {
        "caught_with_history": Rate(40, 86),
        "false_alarms_with_history": Rate(23, 142),
        "caught_without_history": Rate(0, 117),
        "min_readings": 3,
    }
    svg = fig.render(ex, rates, seed=fig.DEFAULT_SEED, sample="5 datasets of 1000 players")
    root = ET.fromstring(svg)  # well-formed
    texts = " ".join(t.text or "" for t in root.iter("{http://www.w3.org/2000/svg}text"))
    assert "40 of 86 (47%)" in texts
    assert "23 of 142 (16%)" in texts
    assert "0 of 117 (0%)" in texts
    assert "never measured" in texts and "would not have this line" in texts
    assert f"Planted adult height {ex.adult_height_cm:.1f} cm" in texts
    # Every label starts inside the drawing.
    for t in root.iter("{http://www.w3.org/2000/svg}text"):
        assert 0 <= float(t.get("x")) <= fig.WIDTH and 0 <= float(t.get("y")) <= fig.HEIGHT
