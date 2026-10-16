"""The what-if in which performance follows maturity (players.PERFORMANCE_FOLLOWS_MATURITY).

It exists to measure the age-fraud rule in its pessimistic case, so it must stay off in every
reported dataset and, when on, change performance and nothing else.
"""

from __future__ import annotations

from data.pipelines.synthetic import players
from data.pipelines.synthetic.config import GeneratorConfig
from data.pipelines.synthetic.dataset import build_dataset


def test_it_is_off_by_default():
    assert players.PERFORMANCE_FOLLOWS_MATURITY is False


def test_it_moves_performance_and_nothing_else(monkeypatch):
    config = GeneratorConfig(seed=4711).scaled(120)
    off = build_dataset(config)
    monkeypatch.setattr(players, "PERFORMANCE_FOLLOWS_MATURITY", True)
    on = build_dataset(config)

    # The answer key is the same players. The ids of the injected impossible rows differ,
    # because the match generator's draws use the shared stream a different number of times.
    assert off.ground_truth["labels"] == on.ground_truth["labels"]
    off_cases, on_cases = off.ground_truth["cases"], on.ground_truth["cases"]
    assert off_cases["late_bloomers"] == on_cases["late_bloomers"]
    assert [c for c in off_cases["fraud"] if c["fraud_type"] == "age_misrepresentation"] == [
        c for c in on_cases["fraud"] if c["fraud_type"] == "age_misrepresentation"
    ]
    assert [m.value for m in off.measurements] == [m.value for m in on.measurements]
    assert [e.metrics for e in off.performance_entries] != [e.metrics for e in on.performance_entries]

    reference = config.population.reference_date
    for profile in on.profiles:
        if profile.is_planted_age_fraud or profile.true_age(reference) >= 18:
            continue
        lift = profile.effective_ability(reference) / profile.ability
        # Early maturers play above their age group, late maturers below it.
        if profile.maturity_offset_years < -0.5:
            assert lift > 1.0
        elif profile.maturity_offset_years > 0.5:
            assert lift < 1.0
