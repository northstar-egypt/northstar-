"""The mirrored-row rule (fraud.detect_result_contradictions) and the planted case behind it.

Who gets flagged is a decision about accusing a child, so every branch of it is pinned here:
a verified row against an unverified one, two unverified rows, two verified rows, a match only
one side logged, and a row with a missing value.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from ml.detectors import fraud
from ml.detectors.features import FeatureSet

DAY = "2025-05-01"


def _row(player, opponent, won, lost, pts_won, pts_lost, *, verified, entry_id=None, day=DAY):
    return {
        "id": entry_id or f"{player}-{opponent}-{won}{lost}",
        "player_id": player,
        "opponent_player_id": opponent,
        "period_start": day,
        "schema_ref": "table_tennis.match.v1",
        "is_validated": verified,
        "metrics": {
            "best_of": 5,
            "sets_won": won,
            "sets_lost": lost,
            "points_won": pts_won,
            "points_lost": pts_lost,
        },
    }


def _features(rows, merged=()):
    players = [
        {
            "id": pid,
            "sex": "male",
            "date_of_birth": "2010-01-01",
            "primary_sport": "table_tennis",
            "status": "merged" if pid in merged else "active",
        }
        for pid in ("a", "b", "c")
    ]
    return FeatureSet("unused", raw={"players": players, "performance_entries": rows})


def test_the_unverified_side_of_a_contradiction_is_flagged():
    # Both rows say "I lost 1-3", so they cannot both be true. a's is coach logged, b's is not.
    rows = [
        _row("a", "b", 1, 3, 40, 45, verified=True),
        _row("b", "a", 1, 3, 40, 45, verified=False),
    ]
    flagged = fraud.detect_result_contradictions(_features(rows))
    assert set(flagged) == {"b"}
    assert "verified row" in flagged["b"]


def test_two_unverified_rows_flag_both_without_saying_who_lied():
    rows = [
        _row("a", "b", 3, 1, 45, 40, verified=False),
        _row("b", "a", 3, 1, 45, 40, verified=False),
    ]
    flagged = fraud.detect_result_contradictions(_features(rows))
    assert set(flagged) == {"a", "b"}
    assert all("does not say which one is true" in reason for reason in flagged.values())


def test_two_verified_rows_are_a_data_error_not_fraud():
    rows = [
        _row("a", "b", 3, 1, 45, 40, verified=True),
        _row("b", "a", 3, 1, 45, 40, verified=True),
    ]
    assert fraud.detect_result_contradictions(_features(rows)) == {}


def test_rows_that_mirror_are_not_flagged():
    rows = [
        _row("a", "b", 3, 1, 45, 40, verified=False),
        _row("b", "a", 1, 3, 40, 45, verified=False),
    ]
    assert fraud.detect_result_contradictions(_features(rows)) == {}


def test_a_match_one_side_never_logged_is_not_evidence():
    """One match in eight is logged by one player only, honestly."""
    rows = [_row("a", "b", 3, 0, 33, 12, verified=False)]
    assert fraud.detect_result_contradictions(_features(rows)) == {}


def test_a_missing_value_is_unknown_not_a_contradiction():
    bad = _row("b", "a", 1, 3, 40, 45, verified=False)
    del bad["metrics"]["points_lost"]
    rows = [_row("a", "b", 1, 3, 40, 45, verified=True), bad]
    assert fraud.detect_result_contradictions(_features(rows)) == {}


def test_an_extra_row_that_agrees_means_a_duplicate_entry_not_a_changed_result():
    rows = [
        _row("a", "b", 3, 1, 45, 40, verified=True, entry_id="a1"),
        _row("b", "a", 1, 3, 40, 45, verified=True, entry_id="b1"),
        _row("b", "a", 3, 1, 45, 40, verified=False, entry_id="b2"),
    ]
    assert fraud.detect_result_contradictions(_features(rows)) == {}


def test_merged_records_are_left_out():
    rows = [
        _row("a", "c", 1, 3, 40, 45, verified=True),
        _row("c", "a", 1, 3, 40, 45, verified=False),
    ]
    assert fraud.detect_result_contradictions(_features(rows, merged={"c"})) == {}


# ---------------------------------------------------------------------------
# The planted case (data/pipelines/synthetic/planted.py plant_result_tampering)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pair():
    from data.pipelines.synthetic.config import GeneratorConfig
    from data.pipelines.synthetic.dataset import build_dataset

    on = GeneratorConfig(seed=4711)
    off = replace(on, planted=replace(on.planted, n_result_tampering=0))
    return build_dataset(on), build_dataset(off)


def test_tampering_changes_only_the_tampered_rows(pair):
    on, off = pair
    tampered = {
        eid
        for c in on.cases.fraud
        if c.fraud_type == "result_tampering"
        for eid in c.detail["tampered_entry_ids"]
    }
    planted = sum(1 for c in on.cases.fraud if c.fraud_type == "result_tampering")
    assert len(tampered) == planted >= 1

    def rows(ds):
        return {str(r.id): (r.metrics, r.source, r.is_validated) for r in ds.performance_entries}

    a, b = rows(on), rows(off)
    assert a.keys() == b.keys()
    assert {k for k in a if a[k] != b[k]} == tampered
    assert [r.measured_at for r in on.measurements] == [r.measured_at for r in off.measurements]
    other = [c.to_dict() for c in on.cases.fraud if c.fraud_type != "result_tampering"]
    assert other == [c.to_dict() for c in off.cases.fraud]


def test_every_planted_tampering_is_a_contradiction_the_rule_can_see(pair, tmp_path):
    from data.pipelines.synthetic.ground_truth import write as write_ground_truth
    from data.pipelines.synthetic.writer import export_json

    on, _ = pair
    export_json(on, tmp_path)
    write_ground_truth(on.ground_truth, tmp_path / "ground_truth.json")
    features = FeatureSet(tmp_path)
    planted = {c.player_id for c in on.cases.fraud if c.fraud_type == "result_tampering"}
    contradicting = {
        str(row["player_id"]) for pair_ in fraud.contradicting_matches(features) for row in pair_
    }
    assert planted <= contradicting
    assert planted <= set(fraud.detect_result_contradictions(features))


def test_two_matches_on_one_day_are_paired_off_before_judging():
    """Found on reported seed 1000: a pair met twice in a day; one match's rows agreed and the
    other's contradicted. The first version saw the agreeing pair and let the day pass."""
    rows = [
        _row("a", "b", 1, 3, 40, 45, verified=True, entry_id="a1"),
        _row("b", "a", 3, 1, 45, 40, verified=True, entry_id="b1"),
        _row("a", "b", 4, 1, 44, 30, verified=True, entry_id="a2"),
        _row("b", "a", 4, 1, 44, 30, verified=False, entry_id="b2"),
    ]
    assert set(fraud.detect_result_contradictions(_features(rows))) == {"b"}


def test_no_planted_tampering_is_against_a_merged_record(pair):
    """Found on reported seed 1013: the rule rightly ignores merged records, so the generator
    must not plant a contradiction it can never show."""
    on, _ = pair
    merged = {str(p.id) for p in on.profiles if p.player.status == "merged"}
    for c in on.cases.fraud:
        if c.fraud_type == "result_tampering":
            assert c.detail["opponent_player_id"] not in merged
