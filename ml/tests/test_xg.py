"""ml/xg: features of a shot, and that the models and their scoring behave. Invented shots in
StatsBomb's format only (no real data in the repository)."""

from __future__ import annotations

import math
import random

import numpy as np

from ml.xg import features as feats
from ml.xg import model


def _shot(x, y, *, body="Right Foot", kind="Open Play", frame=None, key=None, period=1, **extra):
    e = {"id": "s", "type": {"name": "Shot"}, "period": period, "location": [x, y],
         "play_pattern": {"name": "Regular Play"},
         "shot": {"body_part": {"name": body}, "type": {"name": kind}, "technique": {"name": "Normal"},
                  "outcome": {"name": "Goal"}, "end_location": [120, 40, 1], "freeze_frame": frame or []}}
    if key:
        e["shot"]["key_pass_id"] = key
    e["shot"].update(extra)
    return e


KEEPER = {"location": [118.0, 40.0], "position": {"name": "Goalkeeper"}, "teammate": False}


def test_geometry():
    f = feats.features(_shot(108.0, 40.0, frame=[KEEPER]), {})
    assert math.isclose(f["distance"], 12.0)
    assert math.isclose(f["angle"], 2 * math.atan(4 / 12))
    assert f["angle"] > feats.features(_shot(108.0, 10.0, frame=[KEEPER]), {})["angle"]
    assert f["keeper_off_line"] == 2.0 and f["keeper_off_centre"] == 0.0


def test_defenders_in_the_cone_and_the_keeper():
    blocker = {"location": [114.0, 40.0], "position": {"name": "Center Back"}, "teammate": False}
    wide = {"location": [110.0, 70.0], "position": {"name": "Left Back"}, "teammate": False}
    mate = {"location": [115.0, 39.0], "position": {"name": "Center Forward"}, "teammate": True}
    f = feats.features(_shot(108.0, 40.0, frame=[KEEPER, blocker, wide, mate]), {})
    assert f["defenders_in_cone"] == 1.0  # the centre back; not the keeper, not the wide back
    assert f["players_in_cone"] == 3.0  # keeper, centre back and team-mate
    assert math.isclose(f["nearest_defender"], 6.0)
    empty = feats.features(_shot(108.0, 40.0), {})
    assert empty["keeper_to_shooter"] == 120.0  # no keeper in the frame: an empty net


def test_how_the_chance_was_made():
    cross = {"id": "k", "pass": {"cross": True, "height": {"name": "High Pass"}}}
    through = {"id": "t", "pass": {"technique": {"name": "Through Ball"}}}
    assert feats.features(_shot(100, 40, key="k"), {"k": cross})["assist"] == "cross"
    assert feats.features(_shot(100, 40, key="t"), {"t": through})["assist"] == "through_ball"
    assert feats.features(_shot(100, 40), {})["assist"] == "none"
    assert feats.features(_shot(100, 40, body="Head"), {})["body_part"] == "head"


def test_penalties_and_shootouts_are_not_modelled():
    assert feats.is_modelled(_shot(100, 40))
    assert not feats.is_modelled(_shot(108, 40, kind="Penalty"))
    assert not feats.is_modelled(_shot(100, 40, period=5))


def test_nothing_after_the_shot_leaks_in():
    a = feats.features(_shot(100, 40, frame=[KEEPER]), {})
    b_event = _shot(100, 40, frame=[KEEPER])
    b_event["shot"]["outcome"] = {"name": "Off T"}
    b_event["shot"]["end_location"] = [120, 70]
    assert a == feats.features(b_event, {})
    assert len(feats.vector(a)) == len(feats.names())


def test_the_models_learn_an_invented_rule_and_are_scored():
    """Shots whose chance falls with distance: every model should beat a constant guess, and the
    scoring and the bootstrap should run end to end."""
    rng = random.Random(1)
    rows = []
    for i in range(1500):
        x, y = rng.uniform(80, 118), rng.uniform(15, 65)
        f = feats.features(_shot(x, y, frame=[KEEPER]), {})
        p = 1 / (1 + math.exp(0.25 * f["distance"] - 2.5))
        rows.append({"match": i // 25, "features": f, "goal": int(rng.random() < p), "statsbomb_xg": p})
    train, test = rows[:1000], rows[1000:]
    y = np.array([r["goal"] for r in test])
    constant = np.full(len(test), np.mean([r["goal"] for r in train]))
    for kind in ("baseline", "logistic", "boosted"):
        fitted = model.fit(kind, None if kind != "logistic" else 1.0, train)
        p = fitted.predict_proba(model.matrix(test, kind))[:, 1]
        assert model.scores(y, p)["log_loss"] < model.scores(y, constant)["log_loss"]
    mean, low, high = model.bootstrap_difference(test, constant, np.array([r["statsbomb_xg"] for r in test]), rounds=200)
    assert low <= mean <= high and mean > 0  # the constant is worse than the true chance


def test_app_predictions_cover_every_shot_and_are_out_of_fold():
    """predict_for_app: every training shot gets a value from a model that never saw its match,
    every other shot a value from the full model."""
    rng = random.Random(2)
    def row(i, match):
        x, y = rng.uniform(85, 118), rng.uniform(20, 60)
        f = feats.features(_shot(x, y, frame=[KEEPER]), {})
        return {"id": f"s{i}", "match": match, "features": f, "goal": int(rng.random() < 0.12)}
    train = [row(i, i // 20) for i in range(600)]
    others = [row(1000 + i, 500 + i // 20) for i in range(60)]
    values = model.predict_for_app(train, others)
    assert set(values) == {r["id"] for r in train + others}
    assert all(0.0 < v < 1.0 for v in values.values())
