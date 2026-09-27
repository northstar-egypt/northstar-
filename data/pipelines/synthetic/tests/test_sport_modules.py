"""Every generated performance row against its sport module.

The planted "implausible self-reported performance" fraud rows are the only rows in a
dataset that are impossible by construction, and ingest validation should catch exactly them.
Not fewer, because then an impossible record gets stored as real; not more, because every
extra rejection is a legitimate record thrown away.
"""

from __future__ import annotations

import pytest

from data.pipelines.synthetic.config import GeneratorConfig
from data.pipelines.synthetic.dataset import build_dataset
from data.pipelines.synthetic.orm import sports


@pytest.fixture(scope="module", params=[20260827, 7])
def dataset(request):
    return build_dataset(GeneratorConfig(seed=request.param).scaled(160))


def test_validation_rejects_exactly_the_planted_rows(dataset):
    rejected = {
        str(e.id) for e in dataset.performance_entries if sports.validate(e.metrics, e.schema_ref)
    }
    assert rejected == set(dataset.ground_truth["flagged_performance_entry_ids"])


def test_every_carrier_gets_rows_of_their_own_sport(dataset):
    """A table tennis carrier used to be given football rows."""
    sport = {str(p.id): p.primary_sport for p in dataset.players}
    planted = set(dataset.ground_truth["flagged_performance_entry_ids"])
    for e in dataset.performance_entries:
        if str(e.id) in planted:
            assert e.schema_ref.split(".")[0] == sport[str(e.player_id)]


def test_table_tennis_rows_are_finished_matches(dataset):
    planted = set(dataset.ground_truth["flagged_performance_entry_ids"])
    rows = [
        e.metrics
        for e in dataset.performance_entries
        if e.sport == "table_tennis" and str(e.id) not in planted
    ]
    assert rows, "no table tennis rows, so the test proves nothing"
    for m in rows:
        target = m["best_of"] // 2 + 1
        assert max(m["sets_won"], m["sets_lost"]) == target
        assert min(m["sets_won"], m["sets_lost"]) < target


def test_tier_only_where_the_sport_module_uses_it(dataset):
    """Table tennis players once carried a football tier and showed "youth tier" on screen."""
    for player in dataset.players:
        if not sports.registry()[player.primary_sport].uses_tier:
            assert player.tier is None, player.primary_sport
