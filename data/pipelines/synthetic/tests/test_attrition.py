"""Simulated release at 14 must be opt-in and must change nothing but what it says it does.

The first property protects every number already reported: the committed dataset has to be
identical whether or not this module exists. The second is what makes the attrition variant
a fair comparison: the players who were not released must have exactly the rows they would
have had anyway, so any difference in a backtest is the release and nothing else.
"""

from __future__ import annotations

from datetime import date

import pytest

from data.pipelines.synthetic.config import GeneratorConfig
from data.pipelines.synthetic.dataset import build_dataset


def _rows(dataset) -> dict:
    return {
        "measurements": {(str(m.player_id), m.measured_at, m.metric, float(m.value)) for m in dataset.measurements},
        "performance": {str(e.id) for e in dataset.performance_entries},
    }


@pytest.fixture(scope="module")
def pair():
    config = GeneratorConfig(seed=31337).scaled(160)
    plain = build_dataset(config)
    released = build_dataset(
        GeneratorConfig(
            seed=config.seed,
            name_locale=config.name_locale,
            population=config.population,
            organizations=config.organizations,
            measurements=config.measurements,
            performance=config.performance,
            planted=config.planted,
            accounts=config.accounts,
            attrition=True,
        )
    )
    return plain, released


def test_off_by_default():
    assert GeneratorConfig().attrition is False


def test_default_answer_key_has_no_attrition_section(pair):
    plain, _ = pair
    assert "attrition" not in plain.ground_truth


def test_released_players_have_nothing_after_their_review(pair):
    _, released = pair
    cases = released.ground_truth["attrition"]["released"]
    assert cases, "nobody was released, so the test proves nothing"
    released_on = {c["player_id"]: date.fromisoformat(c["released_on"]) for c in cases}
    for m in released.measurements:
        if str(m.player_id) in released_on:
            assert m.measured_at <= released_on[str(m.player_id)]


def test_everyone_else_is_untouched(pair):
    plain, released = pair
    gone = {c["player_id"] for c in released.ground_truth["attrition"]["released"]}
    keep = lambda rows: {r for r in rows if r[0] not in gone}  # noqa: E731
    assert keep(_rows(plain)["measurements"]) == keep(_rows(released)["measurements"])
    # Same players, same ids, same planted cases.
    assert [str(p.id) for p in plain.players] == [str(p.id) for p in released.players]
    assert plain.ground_truth["labels"] == released.ground_truth["labels"]


def test_release_favours_the_small(pair):
    _, released = pair
    zs = [c["height_z"] for c in released.ground_truth["attrition"]["released"]]
    assert sum(zs) / len(zs) < 0
