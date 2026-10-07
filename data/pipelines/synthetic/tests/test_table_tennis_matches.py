"""Table tennis matches are played between two players, and say who the opponent was.

See docs/decisions/0004-table-tennis-opponent-strength.md. A rating is only as good as the
matches it is built from, so these pin down what the generator promises: the two rows of a
match agree, the opponent is a real table tennis player of the same gender, an outsider leaves
no trace, and the stronger player usually wins.
"""

from __future__ import annotations

import collections

import pytest

from data.pipelines.synthetic import performance
from data.pipelines.synthetic.config import GeneratorConfig
from data.pipelines.synthetic.dataset import build_dataset


@pytest.fixture(scope="module", params=[20260827, 7])
def dataset(request):
    return build_dataset(GeneratorConfig(seed=request.param))


def _matches(dataset):
    planted = set(dataset.ground_truth["flagged_performance_entry_ids"])
    return [
        e
        for e in dataset.performance_entries
        if e.sport == "table_tennis" and str(e.id) not in planted
    ]


def _mirrors(a, b) -> bool:
    x, y = a.metrics, b.metrics
    return (
        x["best_of"] == y["best_of"]
        and (x["sets_won"], x["sets_lost"]) == (y["sets_lost"], y["sets_won"])
        and (x["points_won"], x["points_lost"]) == (y["points_lost"], y["points_won"])
    )


def test_opponent_is_another_table_tennis_player_of_the_same_gender(dataset):
    players = {p.id: p for p in dataset.players}
    rows = [e for e in _matches(dataset) if e.opponent_player_id]
    assert rows, "no match between two registered players, so the test proves nothing"
    for e in rows:
        opponent = players[e.opponent_player_id]
        assert e.opponent_player_id != e.player_id
        assert opponent.primary_sport == "table_tennis"
        assert opponent.sex == players[e.player_id].sex


def test_football_rows_never_name_an_opponent_player(dataset):
    assert all(
        e.opponent_player_id is None for e in dataset.performance_entries if e.sport == "football"
    )


def test_both_rows_of_a_match_tell_the_same_result(dataset):
    """Most registered matches are logged by both players, and the two rows mirror."""
    by_key = collections.defaultdict(list)
    for e in _matches(dataset):
        if e.opponent_player_id:
            by_key[(e.player_id, e.opponent_player_id, e.period_start)].append(e)

    rows = [e for group in by_key.values() for e in group]
    mirrored = 0
    for e in rows:
        others = by_key.get((e.opponent_player_id, e.player_id, e.period_start), [])
        if others:
            assert any(_mirrors(e, o) for o in others), "the two rows of a match disagree"
            mirrored += 1
    # One match in eight is logged by only one side (TT_MISSING_MIRROR).
    share = mirrored / len(rows)
    assert 0.8 < share < 0.97, f"{share:.0%} of registered matches have both rows"


def test_about_a_third_of_matches_are_against_outsiders(dataset):
    """An outsider gives one row; a registered match gives up to two."""
    rows = _matches(dataset)
    outside = sum(1 for e in rows if e.opponent_player_id is None)
    registered = len(rows) - outside
    matches = outside + registered / (2 - performance.TT_MISSING_MIRROR)
    assert 0.25 < outside / matches < 0.42


def test_the_stronger_player_usually_wins(dataset):
    """The signal a rating has to recover is there, and is not a certainty."""
    ability = dataset.ground_truth["table_tennis_ability"]
    decided = favourite_won = 0
    for e in _matches(dataset):
        if not e.opponent_player_id:
            continue
        mine, theirs = ability[str(e.player_id)], ability[str(e.opponent_player_id)]
        if abs(mine - theirs) < 0.05:
            continue
        decided += 1
        won = e.metrics["sets_won"] > e.metrics["sets_lost"]
        favourite_won += won == (mine > theirs)
    share = favourite_won / decided
    assert 0.6 < share < 0.95, f"the favourite won {share:.0%} of matches"


def test_ground_truth_holds_the_ability_of_every_table_tennis_player(dataset):
    table_tennis = {str(p.id) for p in dataset.players if p.primary_sport == "table_tennis"}
    assert set(dataset.ground_truth["table_tennis_ability"]) == table_tennis


def test_table_tennis_is_on_its_own_random_stream(monkeypatch):
    """Changing how table tennis is played must not move a single football row or reading.

    Before table tennis had its own stream, any change to it shifted every row drawn after it,
    and with them the published detector and forecast numbers.
    """
    config = GeneratorConfig(seed=11).scaled(120)
    before = build_dataset(config)
    monkeypatch.setattr(performance, "TT_EXTERNAL_SHARE", 0.6)
    monkeypatch.setattr(performance, "TT_MISSING_MIRROR", 0.4)
    after = build_dataset(config)

    # Football rows are drawn before table tennis, so they alone would prove nothing. What is
    # drawn after it on the main stream is what a shared stream would move: the planted
    # football fraud rows, consents and the audit log.
    def football(ds):
        return [(e.id, e.metrics) for e in ds.performance_entries if e.sport == "football"]

    def after_table_tennis(ds):
        return (
            [(c.id, c.granted, c.guardian_name, c.valid_from) for c in ds.consents],
            [(a.id, a.action, a.created_at) for a in ds.audit_logs],
        )

    assert football(before) == football(after)
    assert after_table_tennis(before) == after_table_tennis(after)
    assert [(m.id, m.value) for m in before.measurements] == [
        (m.id, m.value) for m in after.measurements
    ]
    assert before.ground_truth["cases"] == after.ground_truth["cases"]
    tt = lambda ds: [e.metrics for e in ds.performance_entries if e.sport == "table_tennis"]  # noqa: E731
    assert tt(before) != tt(after), "the change did nothing, so the test proves nothing"
