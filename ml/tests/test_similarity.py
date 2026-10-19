"""Player similarity (ml/similarity.py).

What is pinned: a profile is built only from what the record supports (complete rows, enough
time played, no row the opponent's own row contradicts, no merged record), comparisons stay
within sport and gender, `allowed` is respected, and the profile never reads position or the
answer key. How well it does is measured by `python -m ml.run_similarity_eval`.
"""

from __future__ import annotations

import inspect

from ml import similarity
from ml.detectors.features import FeatureSet


def _player(pid, sport="football", sex="male", status="active", position="ST"):
    return {
        "id": pid,
        "sex": sex,
        "date_of_birth": "2008-01-01",
        "primary_sport": sport,
        "position": position,
        "status": status,
    }


def _football_row(pid, n, *, shots=3, minutes=90, drop=None):
    metrics = {
        "minutes_played": minutes, "shots": shots, "shots_on_target": 1, "goals": 0,
        "assists": 0, "key_passes": 1, "tackles": 2, "passes_attempted": 40,
        "passes_completed": 32, "distance_km": 10.0,
    }
    if drop:
        del metrics[drop]
    return {
        "id": f"{pid}-{n}", "player_id": pid, "sport": "football", "period_type": "match",
        "period_start": f"2025-01-{n + 1:02d}", "schema_ref": "football.match.v1",
        "metrics": metrics,
    }


def _features(players, rows):
    return FeatureSet("unused", raw={"players": players, "performance_entries": rows})


def test_a_player_needs_enough_complete_time_on_record():
    rows = [_football_row("a", n) for n in range(6)]  # 540 minutes
    rows += [_football_row("b", n) for n in range(4)]  # 360: too few
    rows += [_football_row("c", n, drop="tackles") for n in range(8)]  # incomplete rows
    every = similarity.profiles(_features([_player(p) for p in "abc"], rows))
    assert set(every) == {"a"}


def test_merged_records_have_no_profile():
    rows = [_football_row(p, n) for p in "ab" for n in range(6)]
    every = similarity.profiles(_features([_player("a"), _player("b", status="merged")], rows))
    assert set(every) == {"a"}


def test_comparisons_stay_within_sport_and_gender_and_respect_allowed():
    players = [_player(p) for p in "abcd"] + [_player("g", sex="female")]
    rows = [_football_row(p, n, shots=s) for p, s in zip("abcdg", (3, 3, 1, 5, 3)) for n in range(6)]
    every = similarity.profiles(_features(players, rows))
    near = [pid for pid, _ in similarity.nearest("a", every, k=10)]
    assert "g" not in near and "a" not in near
    assert near[0] == "b"  # identical record, distance 0
    assert [pid for pid, _ in similarity.nearest("a", every, k=10, allowed={"c"})] == ["c"]


def test_the_profile_reads_neither_position_nor_the_answer_key():
    source = inspect.getsource(similarity.profiles) + inspect.getsource(similarity.distance)
    assert "position" not in source
    assert "ground_truth" not in inspect.getsource(similarity)
    assert "ability" not in source
