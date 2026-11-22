"""Tests for the learned detectors (ml/challengers/learned.py).

These guard the mechanics on small invented players, not the result, which is in ml/README.md:

- the split is by dataset, and no seed plays two roles;
- the model reads only the features the rules read, never gender and never the answer key;
- it judges only players the rule could judge;
- it learns a planted pattern and finds it in a dataset it was not trained on (the test it can
  fail: misaligned labels or a broken feature row would make it guess);
- the threshold is chosen as the docstring says, ties going to fewer flags;
- a model that does not score the calibration seeds as the frozen file says is refused.

Skips cleanly when scikit-learn or xgboost is not installed, as the other challenger tests do.
"""

from __future__ import annotations

import copy
import random
from dataclasses import fields
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("sklearn")
pytest.importorskip("xgboost")

from ml.challengers import learned  # noqa: E402
from ml.challengers.learned import Counts  # noqa: E402
from ml.detectors.features import PlayerFeatures  # noqa: E402

START = date(2024, 1, 1)


def _player(
    pid: str,
    *,
    age: float = 14.0,
    height_z: float | None = 0.0,
    velocity: float = 5.0,
    velocity_z: float | None = 0.0,
    output_z: float | None = 0.0,
    readings: int = 3,
    gender: str = "male",
) -> PlayerFeatures:
    pf = PlayerFeatures(
        player_id=pid, player={"id": pid, "sex": gender, "date_of_birth": "2010-05-01"}
    )
    pf.heights = [(START + timedelta(days=120 * i), 150.0 + i) for i in range(readings)]
    pf.stated_age = age
    pf.height_z_mean = height_z
    pf.height_z_last = height_z
    pf.height_z_min = height_z
    pf.growth_velocity = velocity
    pf.recent_velocity = velocity
    pf.velocity_z = velocity_z
    pf.maturity_mismatch = (
        None if height_z is None or velocity_z is None else height_z - velocity_z
    )
    pf.output_z = output_z
    return pf


def _features(players: list[PlayerFeatures]) -> SimpleNamespace:
    return SimpleNamespace(
        players={p.player_id: p for p in players}, raw={"players": [p.player for p in players]}
    )


def _world(seed: int, n: int = 150) -> learned.Labelled:
    """An invented dataset with a clean pattern for each detector.

    One player in ten is a late bloomer (short and growing fast), one in ten an age cheat (tall,
    no longer growing, and outplaying the age group). Everyone else is drawn so that no single
    number separates them: plenty of them are short, or tall, or slow growing.
    """
    rng = random.Random(seed)
    players, late, cheats = [], set(), set()
    for i in range(n):
        pid = f"w{seed}-p{i}"
        age = rng.uniform(11.5, 16.5)
        if i % 10 == 0:
            late.add(pid)
            pf = _player(pid, age=age, height_z=rng.uniform(-2.0, -1.2),
                         velocity=rng.uniform(7.5, 9.5), velocity_z=rng.uniform(1.0, 2.0),
                         output_z=rng.uniform(-0.5, 0.5))
        elif i % 10 == 5:
            cheats.add(pid)
            pf = _player(pid, age=age, height_z=rng.uniform(1.4, 2.5),
                         velocity=rng.uniform(0.5, 2.0), velocity_z=rng.uniform(-2.0, -1.2),
                         output_z=rng.uniform(1.2, 2.2))
        else:
            pf = _player(pid, age=age, height_z=rng.uniform(-2.0, 2.0),
                         velocity=rng.uniform(1.0, 6.0), velocity_z=rng.uniform(-1.0, 1.0),
                         output_z=rng.uniform(-1.0, 0.8))
        players.append(pf)
    ids = {p.player_id for p in players}
    return learned.Labelled(
        seed=seed,
        features=_features(players),
        truth={"late_bloomer": late, "age_fraud": cheats},
        population={"late_bloomer": ids, "age_fraud": ids},
    )


TRAIN = [_world(s) for s in (1, 2, 3, 4)]
CALIBRATION = [_world(50)]
UNSEEN = _world(99)


# ---------------------------------------------------------------------------
# The split
# ---------------------------------------------------------------------------


def test_the_documented_seed_sets_do_not_overlap():
    learned.check_seeds(learned.TRAIN_SEEDS, learned.CALIBRATION_SEEDS, learned.REPORTED_SEEDS)
    assert learned.CALIBRATION_SEEDS == (101, 202, 303)
    assert sorted(learned.REPORTED_SEEDS) == sorted(
        [20260827, 7, 99, 404, 555, *range(1000, 1015)]
    )
    assert len(learned.REPORTED_SEEDS) == 20


@pytest.mark.parametrize(
    "train, calibration, reported",
    [([2000, 101], [101, 202], [7]), ([2000], [202], [202, 7]), ([7, 2000], [202], [7])],
)
def test_a_seed_in_two_roles_is_refused(train, calibration, reported):
    with pytest.raises(ValueError, match="no dataset may play two roles"):
        learned.check_seeds(train, calibration, reported)


# ---------------------------------------------------------------------------
# What the model sees
# ---------------------------------------------------------------------------


def test_every_feature_comes_from_the_rules_feature_set():
    """Nothing the answer key knows can be an input: every input is a PlayerFeatures field."""
    known = {f.name for f in fields(PlayerFeatures)}
    assert set(learned.FEATURES) - {"readings"} <= known
    assert set(learned.MAY_BE_MISSING) <= set(learned.FEATURES)
    assert len(learned.vector(_player("a"))) == len(learned.COLUMNS)


def test_gender_is_not_an_input():
    assert learned.vector(_player("a", gender="female")) == learned.vector(_player("a"))


def test_a_missing_value_is_marked_not_dropped():
    """Zero minutes played means no output score: filled with 0 and marked missing."""
    with_output = learned.vector(_player("a", output_z=1.5))
    without = learned.vector(_player("a", output_z=None))
    value = learned.COLUMNS.index("output_z")
    marker = learned.COLUMNS.index("output_z missing")
    assert (with_output[value], with_output[marker]) == (1.5, 0.0)
    assert (without[value], without[marker]) == (0.0, 1.0)


def test_only_players_the_rule_could_judge_are_eligible():
    players = [
        _player("ok"),
        _player("adult", age=25.0),
        _player("child", age=9.0),
        _player("two_readings", readings=2),
        _player("no_height_z", height_z=None),
        _player("nineteen", age=19.0),
    ]
    features = _features(players)
    late = {pf.player_id for pf in learned.eligible(features, "late_bloomer")}
    age = {pf.player_id for pf in learned.eligible(features, "age_fraud")}
    assert late == {"ok"}  # the late-bloomer rule stops at 18.5
    assert age == {"ok", "nineteen"}  # the age rule runs to 19


def test_everything_the_rules_flag_is_eligible():
    """The model is never given fewer players than the rule it is compared with."""
    for data in (UNSEEN, *TRAIN):
        for detector in learned.DETECTORS:
            flagged = set(learned.rule(data.features, detector))
            assert flagged <= {pf.player_id for pf in learned.eligible(data.features, detector)}


def test_training_rows_follow_the_scored_population():
    data = _world(7, n=20)
    cheat = sorted(data.truth["age_fraud"])[0]
    data.population["age_fraud"] = data.population["age_fraud"] - {cheat}
    _, with_all = learned.training_rows([data], "late_bloomer")
    _, without_one = learned.training_rows([data], "age_fraud")
    assert len(without_one) == len(with_all) - 1
    assert without_one.sum() == len(data.truth["age_fraud"]) - 1


# ---------------------------------------------------------------------------
# The models
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", learned.MODELS)
@pytest.mark.parametrize("detector", learned.DETECTORS)
def test_it_finds_the_planted_pattern_in_a_dataset_it_never_saw(detector, model):
    fitted = learned.fit(TRAIN, detector, model)
    flagged = set(fitted.detect(UNSEEN.features, 0.5))
    score = learned.score_ids("", flagged, UNSEEN.truth[detector], UNSEEN.population[detector])
    assert score.recall >= 0.9
    assert score.precision >= 0.9


@pytest.mark.parametrize("model", learned.MODELS)
def test_fitting_twice_gives_the_same_model(model):
    first = learned.fit(TRAIN, "late_bloomer", model).scores(UNSEEN.features)
    second = learned.fit(TRAIN, "late_bloomer", model).scores(UNSEEN.features)
    assert first == second


def test_training_without_a_planted_case_is_an_error_not_a_silent_model():
    data = _world(8, n=30)
    data.truth["late_bloomer"] = set()
    with pytest.raises(ValueError, match="both planted and unplanted"):
        learned.fit([data], "late_bloomer", "logistic")


def test_an_ineligible_player_is_never_flagged_whatever_the_score():
    fitted = learned.fit(TRAIN, "late_bloomer", "logistic")
    textbook = _player("adult", age=25.0, height_z=-1.8, velocity=9.0, velocity_z=2.0)
    assert fitted.detect(_features([textbook]), 0.05) == {}


def test_empty_and_single_player_datasets():
    fitted = learned.fit(TRAIN, "age_fraud", "boosting")
    assert fitted.scores(_features([])) == {}
    one = _player("one", height_z=2.2, velocity=1.0, velocity_z=-1.8, output_z=1.8)
    scores = fitted.scores(_features([one]))
    assert set(scores) == {"one"} and 0.0 <= scores["one"] <= 1.0


def test_the_flag_says_score_not_chance_and_handles_missing_values():
    fitted = learned.fit(TRAIN, "age_fraud", "logistic")
    pf = _player("x", height_z=2.0, velocity_z=None, output_z=None)
    reason = learned.explain(pf, fitted, 0.81, 0.6)
    assert "scores this player 0.81" in reason and "flags from 0.60" in reason
    assert "growth rate unknown" in reason and "no output on record" in reason
    assert "chance" not in reason and "probability" not in reason


# ---------------------------------------------------------------------------
# Choosing the threshold
# ---------------------------------------------------------------------------


def test_counts_are_pooled_and_ignore_ids_outside_the_population():
    scored = [
        ({"a": 0.9, "b": 0.6, "c": 0.2}, {"a", "c"}, {"a", "b", "c"}),
        ({"d": 0.7, "outsider": 0.99}, {"d"}, {"d", "e"}),
    ]
    assert learned.counts_at(scored, 0.5) == Counts(tp=2, fp=1, fn=1)


def test_the_threshold_with_the_highest_f1_is_chosen():
    grid = {0.3: Counts(8, 6, 2), 0.5: Counts(7, 2, 3), 0.7: Counts(5, 0, 5)}
    assert learned.choose_threshold(grid) == 0.5


def test_a_cap_on_false_flags_is_respected():
    grid = {0.3: Counts(8, 6, 2), 0.5: Counts(7, 2, 3), 0.7: Counts(5, 0, 5)}
    assert learned.choose_threshold(grid, max_false=1) == 0.7
    assert learned.choose_threshold({0.5: Counts(3, 4, 1)}, max_false=2) is None


def test_ties_go_to_the_higher_threshold_which_flags_fewer():
    assert learned.choose_threshold({0.4: Counts(5, 1, 1), 0.6: Counts(5, 1, 1)}) == 0.6
    assert learned.choose_threshold({0.2: Counts(0, 3, 4), 0.8: Counts(0, 0, 4)}) == 0.8


# ---------------------------------------------------------------------------
# Frozen thresholds and the report
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def frozen() -> dict:
    return learned.calibrate(TRAIN, CALIBRATION)


def test_calibration_records_both_operating_points_and_the_rule(frozen):
    assert frozen["train_seeds"] == [1, 2, 3, 4] and frozen["calibration_seeds"] == [50]
    for detector in learned.DETECTORS:
        assert set(frozen["rule"][detector]) == {"tp", "fp", "fn"}
        for model in learned.MODELS:
            entry = frozen["models"][detector][model]
            assert set(entry["thresholds"]) == set(learned.OPERATING_POINTS)
            assert len(entry["grid"]) == len(learned.THRESHOLDS)
            capped = entry["thresholds"]["no_more_flags"]
            if capped is not None:
                assert entry["grid"][f"{capped:.2f}"][1] <= frozen["rule"][detector]["fp"]


def test_the_model_calibrated_is_the_model_reported(frozen):
    same = learned.fit(TRAIN, "late_bloomer", "logistic")
    assert learned.check_same_model(frozen, same, CALIBRATION) is None

    edited = copy.deepcopy(frozen)
    edited["models"]["late_bloomer"]["logistic"]["grid"]["0.50"][1] += 1  # one more false flag
    with pytest.raises(RuntimeError, match="not exactly the model whose thresholds were chosen"):
        learned.check_same_model(edited, same, CALIBRATION)

    # On another platform the difference can be accepted, and is then described, not hidden.
    described = learned.check_same_model(edited, same, CALIBRATION, strict=False)
    assert "at 1 of 19 thresholds (at most 1 counts apart)" in described
    notes: list[str] = []
    rows = learned.score_reported(edited, TRAIN, CALIBRATION, [UNSEEN], strict=False, notes=notes)
    assert notes == [described]
    assert "Not the frozen model." in learned.render(rows, "test", notes)


def test_the_report_puts_the_rule_first_and_breaks_results_down(frozen):
    rows = learned.score_reported(frozen, TRAIN, CALIBRATION, [UNSEEN, _world(98)])
    for detector in learned.DETECTORS:
        assert rows[detector][0].name == "rule"
        assert len(rows[detector]) >= 2
        for row in rows[detector]:
            assert len(row.per_seed) == 2
            pooled = row.pooled
            by_gender = row.pooled_groups("by_gender")
            assert sum(s.tp for s in by_gender.values()) == pooled.tp
            assert sum(s.fp for s in by_gender.values()) == pooled.fp
            by_age = row.pooled_groups("by_age")
            assert sum(s.support for s in by_age.values()) == pooled.support
    text = learned.render(rows, "test")
    assert "| rule |" in text and "By stated age" in text and "by birth quarter" in text


def test_the_gain_interval_is_paired_and_brackets_the_observed_gain():
    from ml.evaluation.metrics import Score

    rule_row = learned.Row("rule", per_seed=[Score("r", 5, 5, 5, 85)] * 10)
    same = learned.Row("same", per_seed=[Score("s", 5, 5, 5, 85)] * 10)
    assert learned.gain_interval(same, rule_row) == ((0.0, 0.0), (0.0, 0.0))

    better = learned.Row("better", per_seed=[Score("b", 8, 2, 2, 88)] * 5 + [Score("b", 5, 5, 5, 85)] * 5)
    (f1_low, f1_high), (fp_low, fp_high) = learned.gain_interval(better, rule_row)
    observed = better.pooled.f1 - rule_row.pooled.f1
    assert 0.0 <= f1_low <= observed <= f1_high
    assert fp_low <= better.pooled.fp - rule_row.pooled.fp <= fp_high <= 0


def test_importance_names_the_inputs_that_carry_the_pattern():
    """In the invented world a late bloomer is short and growing fast, so shuffling growth or
    height must hurt the model most, and shuffling the number of readings (all 3) not at all."""
    fitted = learned.fit(TRAIN, "late_bloomer", "boosting")
    ranked = learned.importance(fitted, [UNSEEN], repeats=3)
    assert [c for c, _, _ in ranked] != [] and len(ranked) == len(learned.COLUMNS)
    assert [m for _, m, _ in ranked] == sorted((m for _, m, _ in ranked), reverse=True)
    top = {c for c, _, _ in ranked[:3]}
    assert top & {"recent_velocity", "growth_velocity", "velocity_z", "height_z_mean",
                  "height_z_last", "height_z_min", "maturity_mismatch"}
    assert dict((c, m) for c, m, _ in ranked)["readings"] == 0.0


def test_logistic_weights_point_the_way_the_pattern_does():
    fitted = learned.fit(TRAIN, "late_bloomer", "logistic")
    weights = dict(learned.logistic_weights(fitted))
    assert set(weights) == set(learned.COLUMNS)
    assert weights["recent_velocity"] > 0
    assert weights["height_z_mean"] + weights["height_z_last"] + weights["height_z_min"] < 0
    with pytest.raises(ValueError, match="only the logistic regression"):
        learned.logistic_weights(learned.fit(TRAIN, "late_bloomer", "boosting"))


def test_the_commands_run_end_to_end_on_generated_datasets(tmp_path):
    """calibrate writes the file, report reads it back through JSON and scores a dataset, and
    the what-if switch is put back afterwards. Small seeds, so it takes seconds, not minutes."""
    import json

    from data.pipelines.synthetic import players

    frozen_path, report_path = tmp_path / "thresholds.json", tmp_path / "report.json"
    assert learned.main(["calibrate", "--train-seeds", "2000", "2001",
                         "--calibration-seeds", "101", "--out", str(frozen_path)]) == 0
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    assert frozen["train_seeds"] == [2000, 2001] and frozen["calibration_seeds"] == [101]

    ablation_path = tmp_path / "thresholds_no_age.json"
    assert learned.main(["calibrate", "--train-seeds", "2000", "2001", "--calibration-seeds", "101",
                         "--drop", "stated_age", "--out", str(ablation_path)]) == 0
    assert json.loads(ablation_path.read_text(encoding="utf-8"))["dropped"] == ["stated_age"]

    assert learned.main(["report", "--thresholds", str(frozen_path), str(ablation_path), "--seeds", "7",
                         "--performance-follows-maturity", "--json", str(report_path)]) == 0
    assert players.PERFORMANCE_FOLLOWS_MATURITY is False
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert set(report) == set(learned.DETECTORS)
    assert all("rule" in rows for rows in report.values())
    assert all(any("without stated age" in name for name in rows) for rows in report.values())

    with pytest.raises(ValueError, match="two roles"):
        learned.main(["report", "--thresholds", str(frozen_path), "--seeds", "101"])


# ---------------------------------------------------------------------------
# The stated-age ablation
# ---------------------------------------------------------------------------


def test_dropping_stated_age_removes_only_its_column():
    columns = learned.kept(("stated_age",))
    assert len(columns) == len(learned.COLUMNS) - 1
    assert [learned.COLUMNS[i] for i in columns] == [c for c in learned.COLUMNS if c != "stated_age"]
    assert learned.kept() == list(range(len(learned.COLUMNS)))


@pytest.mark.parametrize("name", ["output_z", "velocity_z", "not a feature"])
def test_only_a_feature_that_cannot_be_missing_can_be_dropped(name):
    with pytest.raises(ValueError, match="cannot drop"):
        learned.kept((name,))


def _planted_by_age(world: learned.Labelled) -> learned.Labelled:
    """The same world with the age cheats moved to stated ages 15 to 16.5, as the generator
    plants them in a narrower range than the rule judges: stated age now carries information."""
    for pf in world.features.players.values():
        if pf.player_id in world.truth["age_fraud"]:
            pf.stated_age = 15.0 + (int(pf.player_id.rsplit("p", 1)[1]) % 4) * 0.5
    return world


@pytest.mark.parametrize("model", learned.MODELS)
def test_a_model_without_stated_age_never_reads_it(model):
    """Change every player's stated age (inside the rule's range, so nobody's eligibility
    moves): the ablated model's scores must not move at all.

    The test can fail: the full logistic regression, which gives every input a weight, does
    move. (Boosting may simply not use an input it does not need on these clean invented
    players, so only the logistic model proves the point.)"""
    train = [_planted_by_age(_world(s)) for s in (1, 2, 3, 4)]
    unseen = _planted_by_age(_world(99))
    aged = _planted_by_age(_world(99))
    for pf in aged.features.players.values():
        pf.stated_age = 12.0 if pf.stated_age > 14.0 else 16.0

    without = learned.fit(train, "age_fraud", model, drop=("stated_age",))
    assert without.scores(unseen.features) == without.scores(aged.features)

    if model == "logistic":
        full = learned.fit(train, "age_fraud", model)
        assert full.scores(unseen.features) != full.scores(aged.features)


def test_the_ablation_has_its_own_thresholds_and_its_own_rows(frozen):
    ablated = learned.calibrate(TRAIN, CALIBRATION, drop=("stated_age",))
    assert ablated["dropped"] == ["stated_age"] and "dropped" not in frozen

    full = learned.fit(TRAIN, "late_bloomer", "logistic")
    with pytest.raises(ValueError, match="without"):
        learned.check_same_model(ablated, full, CALIBRATION)  # a file is for one input set

    rows = learned.score_reported([frozen, ablated], TRAIN, CALIBRATION, [UNSEEN])
    for detector in learned.DETECTORS:
        names = [row.name for row in rows[detector]]
        assert names[0] == "rule"
        assert any("without stated age" in n for n in names)
        assert any("without" not in n and n != "rule" for n in names)

    other = dict(ablated, train_seeds=[9])
    with pytest.raises(ValueError, match="different seeds"):
        learned.score_reported([frozen, other], TRAIN, CALIBRATION, [UNSEEN])


@pytest.mark.parametrize(
    "age, band",
    [(9.0, "under 11"), (11.0, "11 to 13"), (12.99, "11 to 13"), (13.0, "13 to 15"),
     (16.5, "15 to 17"), (17.0, "17+"), (25.0, "17+")],
)
def test_age_bands(age, band):
    assert learned.age_band(age) == band
