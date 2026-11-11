"""Tests for the reviewer-feedback learner (ml/feedback.py).

The measured result is in ml/README.md; these guard the mechanics: level 0 is exactly the v1
rule, a simulated reviewer decides as told, and the learner keeps what decisions taught it to
keep, including when every decision went the same way.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("sklearn")

from ml import feedback  # noqa: E402
from ml.detectors.features import PlayerFeatures  # noqa: E402
from ml.detectors.fraud import FraudParams  # noqa: E402
from ml.detectors.late_bloomer import LateBloomerParams  # noqa: E402


def _player(pid: str, velocity: float, *, output_z: float | None = 0.0) -> PlayerFeatures:
    pf = PlayerFeatures(player_id=pid, player={"sex": "male"})
    pf.stated_age = 14.0
    pf.height_z_mean = -1.2
    pf.height_z_last = -1.0
    pf.height_z_min = -1.4
    pf.recent_velocity = velocity
    pf.velocity_z = velocity - 5.0
    pf.maturity_mismatch = -1.0
    pf.output_z = output_z
    return pf


def _features(players: list[PlayerFeatures]):
    return SimpleNamespace(players={p.player_id: p for p in players})


def test_level_zero_is_the_v1_rule():
    assert feedback.NET_LEVELS["late_bloomer"][0] == LateBloomerParams()
    assert feedback.NET_LEVELS["age_fraud"][0] == FraudParams()


def test_each_level_is_looser_than_the_one_before():
    levels = feedback.NET_LEVELS["late_bloomer"]
    for narrow, wide in zip(levels, levels[1:]):
        assert wide.max_height_z_mean > narrow.max_height_z_mean
        assert wide.min_recent_velocity < narrow.min_recent_velocity
    levels = feedback.NET_LEVELS["age_fraud"]
    for narrow, wide in zip(levels, levels[1:]):
        assert wide.min_maturity_mismatch < narrow.min_maturity_mismatch
        assert wide.min_output_z < narrow.min_output_z


def test_a_missing_value_is_marked_not_dropped():
    with_output = feedback.vector(_player("a", 6.0, output_z=1.0))
    without = feedback.vector(_player("a", 6.0, output_z=None))
    assert len(with_output) == len(feedback.FEATURES) + len(feedback._MAY_BE_MISSING)
    assert with_output[-1] == 0.0 and without[-1] == 1.0  # output_z is the last that may be missing


def test_the_simulated_reviewer_decides_as_told():
    players = [_player(f"p{i}", 3.0 + i) for i in range(10)]
    features = _features(players)
    truth = {"p1", "p2"}
    right = feedback.decide(features, {p.player_id for p in players}, truth)
    assert sum(right.confirmed) == 2
    wrong = feedback.decide(features, {p.player_id for p in players}, truth, wrong=1.0)
    assert sum(wrong.confirmed) == 8


def test_the_learner_keeps_what_reviewers_confirmed():
    """Reviewers confirmed the fast growers and dismissed the slow ones; on new players it
    keeps the fast growers."""
    seen = [_player(f"fast{i}", 7.0 + 0.1 * i) for i in range(8)]
    seen += [_player(f"slow{i}", 3.0 + 0.1 * i) for i in range(8)]
    decided = feedback.decide(
        _features(seen), {p.player_id for p in seen}, {p.player_id for p in seen[:8]}
    )
    learner = feedback.Learner(decided)
    new = [_player("new_fast", 7.5), _player("new_slow", 3.2)]
    assert learner.keep(_features(new), {"new_fast", "new_slow"}) == {"new_fast"}


def test_one_sided_decisions_keep_all_or_nothing():
    players = [_player(f"p{i}", 5.0) for i in range(4)]
    ids = {p.player_id for p in players}
    features = _features(players)
    all_confirmed = feedback.Learner(feedback.decide(features, ids, ids))
    assert all_confirmed.keep(features, ids) == ids
    all_dismissed = feedback.Learner(feedback.decide(features, ids, set()))
    assert all_dismissed.keep(features, ids) == set()
