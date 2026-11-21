"""Learned detectors: supervised models for late bloomers and age misrepresentation.

The late-bloomer detector (`ml/detectors/late_bloomer.py`) and the age-misrepresentation rule
(`fraud.detect_age_misrepresentation`) are hand-written rules whose thresholds were tuned on
seeds 101, 202 and 303. This challenger asks whether a model trained on the same features, with
the generator's answer key as labels, beats them honestly. Evaluated by this module's own
command (below); the results go in ml/README.md under "Challenger models".

Every setting in this file except the decision threshold was fixed before the first run on any
seed, and committed before that run, so the history shows nothing was adjusted after seeing a
result. The threshold is the one thing chosen from data, by code, on the calibration seeds only.

What the model reads
--------------------
`FEATURES`: numbers `ml/detectors/features.py` already computes for the rules, and nothing
else. Nothing is derived from the answer key. A value that can be missing (no growth-rate
estimate, too little playing time for an output score) is filled with 0 and marked by its own
0/1 column (`MAY_BE_MISSING`), so "nothing on record" is something the model can learn from
rather than a hole.

Gender is not an input. Every z score is already taken against players of the same gender and
stated age, the rules do not read gender either, and girls are a small share of the synthetic
population, so a gender input would be learned from very few of them. Gender is used after the
fact instead, to break caught cases and false accusations down by it.

Who it judges
-------------
Exactly the players the rule could judge (`eligible`): the rule's own age range, its minimum
number of height readings, and a height z score. A player outside them is never flagged, so the
comparison is about the decision and not about who is looked at. For age misrepresentation the
other two fraud subtypes (impossible metrics, result tampering) are left out of training and
scoring, as the harness leaves them out of the rule's subtype score.

The two models
--------------
- `logistic`: standardised logistic regression, `C=1`, classes weighted to balance. Small, and
  its weights can be read.
- `boosting`: XGBoost, 300 trees of depth 3, learning rate 0.05, minimum child weight 5, 80% of
  the rows and of the columns per tree, positives weighted by negatives over positives,
  `random_state=0`, and one thread, so fitting twice gives the same model.

Planted cases are a few percent of the players, so both models weight them up, and recall is
reported, never accuracy. Because of that weighting the model's output is a score for ranking,
not a calibrated probability, and the sentence on a flag says "score", not "chance".

The split, by dataset and never by player
-----------------------------------------
- train: datasets generated from seeds 2000 to 2049, which are never reported anywhere.
- calibration: 101, 202 and 303, the seeds every rule threshold was tuned on. Used here only to
  choose the decision threshold, and not trained on: a threshold chosen on the model's own
  training players is chosen on scores better than any it will give new players.
- reported: 20260827, 7, 99, 404, 555 and 1000 to 1014, the 20 seeds the rules are published
  on. Scored once, after the thresholds are committed.

The decision threshold
----------------------
A score from `THRESHOLDS` (0.05 to 0.95 in steps of 0.05), chosen on the calibration seeds
pooled, at two operating points:

- `best_f1`: the highest F1.
- `no_more_flags`: the highest F1 among thresholds that flag no more wrong players than the rule
  did on the same calibration seeds. A model replaces a rule only if it wins without more false
  accusations, so this is the operating point that question is asked at.

Ties go to the higher threshold, which flags fewer children. `calibrate` writes both, with the
counts behind them, to `THRESHOLDS_FILE`. `report` refits the models, checks they score the
calibration seeds exactly as the file says (so the model reported is the model calibrated), and
only then scores the reported seeds. XGBoost does not build bit-identical trees on every
operating system, so on another platform the check can fail; `--allow-refit-difference` then
runs anyway and prints how far the refit is from the frozen model. ml/README.md records how
far that is on Linux.

    python -m ml.challengers.learned calibrate
    python -m ml.challengers.learned report
    python -m ml.challengers.learned report --performance-follows-maturity
    python -m ml.challengers.learned explain

`explain` says what drives each model, on the calibration seeds (never the reported ones):
permutation importance for both models, and the logistic regression's weights. It was added
after the reported run and changes nothing the report measured; `check_same_model` proves the
models it explains are the ones reported.

The what-if world (`--performance-follows-maturity`, see "Age misrepresentation, v2" in
ml/README.md) changes only the reported datasets: the models and thresholds are the ones fitted
and chosen in the ordinary world, as the v2 rule's thresholds were. A model that only learned
the generator's quirks falls apart there.
"""

from __future__ import annotations

import json
import random
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import numpy as np

from ml.detectors import fraud, late_bloomer
from ml.detectors.features import FeatureSet, PlayerFeatures
from ml.detectors.fraud import FraudParams
from ml.detectors.late_bloomer import LateBloomerParams
from ml.evaluation import fairness
from ml.evaluation.metrics import Score, score_ids

DETECTORS = ("late_bloomer", "age_fraud")
MODELS = ("logistic", "boosting")
OPERATING_POINTS = ("best_f1", "no_more_flags")

TRAIN_SEEDS = tuple(range(2000, 2050))
CALIBRATION_SEEDS = (101, 202, 303)
REPORTED_SEEDS = (20260827, 7, 99, 404, 555, *range(1000, 1015))

FEATURES = (
    "stated_age",
    "height_z_mean",
    "height_z_last",
    "height_z_min",
    "growth_velocity",
    "recent_velocity",
    "velocity_z",
    "maturity_mismatch",
    "output_z",
    "readings",
)
MAY_BE_MISSING = ("height_z_last", "height_z_min", "velocity_z", "maturity_mismatch", "output_z")
COLUMNS = FEATURES + tuple(f"{name} missing" for name in MAY_BE_MISSING)

THRESHOLDS = tuple(round(0.05 * i, 2) for i in range(1, 20))
THRESHOLDS_FILE = Path(__file__).with_name("learned_thresholds.json")

# The fraud subtypes that are not age misrepresentation. Left out of the age model's training
# and scoring, exactly as `ml/evaluation/harness.py` leaves them out of the rule's age score.
OTHER_FRAUD = ("implausible_self_reported_performance", "result_tampering")

# Stated-age bands for the breakdown, the same as the v2 table in ml/README.md.
AGE_BANDS = ((11.0, 13.0, "11 to 13"), (13.0, 15.0, "13 to 15"), (15.0, 17.0, "15 to 17"))

_MODEL_LABEL = {"logistic": "logistic regression", "boosting": "gradient boosting"}
_DETECTOR_LABEL = {"late_bloomer": "Late bloomer", "age_fraud": "Age misrepresentation"}


# ---------------------------------------------------------------------------
# The split
# ---------------------------------------------------------------------------


def check_seeds(train: Iterable[int], calibration: Iterable[int], reported: Iterable[int]) -> None:
    """Refuse a split in which one dataset plays two roles."""
    roles = {"train": set(train), "calibration": set(calibration), "reported": set(reported)}
    for first, second in (("train", "calibration"), ("train", "reported"), ("calibration", "reported")):
        shared = roles[first] & roles[second]
        if shared:
            raise ValueError(
                f"seeds {sorted(shared)} are in both the {first} and the {second} set; "
                f"the split is by dataset and no dataset may play two roles"
            )


# ---------------------------------------------------------------------------
# What the model sees
# ---------------------------------------------------------------------------


def _gates(detector: str) -> tuple[float, float, int]:
    if detector == "late_bloomer":
        params = LateBloomerParams()
    elif detector == "age_fraud":
        params = FraudParams()
    else:
        raise ValueError(f"unknown detector {detector!r}")
    return params.min_age, params.max_age, params.min_measurements


def eligible(features: FeatureSet, detector: str) -> list[PlayerFeatures]:
    """The players the rule could judge, in a fixed order."""
    low, high, readings = _gates(detector)
    return sorted(
        (
            pf
            for pf in features.players.values()
            if pf.height_z_mean is not None
            and len(pf.heights) >= readings
            and low <= pf.stated_age <= high
        ),
        key=lambda pf: pf.player_id,
    )


def vector(pf: PlayerFeatures) -> list[float]:
    """One player's row, in the order of `COLUMNS`."""
    values = {
        "stated_age": pf.stated_age,
        "height_z_mean": pf.height_z_mean,
        "height_z_last": pf.height_z_last,
        "height_z_min": pf.height_z_min,
        "growth_velocity": pf.growth_velocity,
        "recent_velocity": pf.recent_velocity,
        "velocity_z": pf.velocity_z,
        "maturity_mismatch": pf.maturity_mismatch,
        "output_z": pf.output_z,
        "readings": float(len(pf.heights)),
    }
    row = [0.0 if values[name] is None else float(values[name]) for name in FEATURES]
    row += [1.0 if values[name] is None else 0.0 for name in MAY_BE_MISSING]
    return row


@dataclass
class Labelled:
    """One generated dataset, with what each detector is scored against."""

    seed: int
    features: FeatureSet
    truth: dict[str, set[str]]
    population: dict[str, set[str]]

    @cached_property
    def quarters(self) -> dict[str, str]:
        """{player_id: birth quarter}, for the relative age audit. Computed once per dataset."""
        return fairness.quarters_of(self.features.raw["players"])


def labelled(features: FeatureSet, ground_truth: dict, seed: int) -> Labelled:
    """Read the answer key the way the harness does. Only labels come from it, never inputs."""
    everyone = set(ground_truth["population"]["player_ids"])
    fraud_cases = ground_truth["cases"]["fraud"]
    age = {c["player_id"] for c in fraud_cases if c["fraud_type"] == "age_misrepresentation"}
    other = {c["player_id"] for c in fraud_cases if c["fraud_type"] in OTHER_FRAUD}
    return Labelled(
        seed=seed,
        features=features,
        truth={"late_bloomer": set(ground_truth["labels"]["late_bloomer"]), "age_fraud": age},
        population={"late_bloomer": everyone, "age_fraud": everyone - other},
    )


def training_rows(datasets: Iterable[Labelled], detector: str) -> tuple[np.ndarray, np.ndarray]:
    """Every eligible player in the scored population of every dataset: features and label."""
    rows: list[list[float]] = []
    labels: list[int] = []
    for data in datasets:
        truth, population = data.truth[detector], data.population[detector]
        for pf in eligible(data.features, detector):
            if pf.player_id in population:
                rows.append(vector(pf))
                labels.append(1 if pf.player_id in truth else 0)
    x = np.asarray(rows, dtype=float).reshape(-1, len(COLUMNS))
    return x, np.asarray(labels, dtype=int)


# ---------------------------------------------------------------------------
# The models
# ---------------------------------------------------------------------------


def _estimator(model: str, labels: np.ndarray):
    if model == "logistic":
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        return make_pipeline(
            StandardScaler(),
            LogisticRegression(C=1.0, class_weight="balanced", max_iter=5000),
        )
    if model == "boosting":
        from xgboost import XGBClassifier

        positives = int(labels.sum())
        return XGBClassifier(
            n_estimators=300,
            max_depth=3,
            learning_rate=0.05,
            min_child_weight=5,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            scale_pos_weight=(len(labels) - positives) / positives,
            tree_method="hist",
            eval_metric="logloss",
            random_state=0,
            n_jobs=1,
        )
    raise ValueError(f"unknown model {model!r}")


@dataclass
class Learned:
    """A fitted model for one detector."""

    detector: str
    model: str
    estimator: object

    def scores(self, features: FeatureSet) -> dict[str, float]:
        """A score between 0 and 1 for every eligible player. Higher means flag sooner."""
        players = eligible(features, self.detector)
        if not players:
            return {}
        x = np.asarray([vector(pf) for pf in players], dtype=float)
        scored = self.estimator.predict_proba(x)[:, 1]
        return {pf.player_id: float(value) for pf, value in zip(players, scored)}

    def detect(self, features: FeatureSet, threshold: float) -> dict[str, str]:
        """{player_id: reason} for every player scored at or above the threshold."""
        return {
            pid: explain(features.players[pid], self, score, threshold)
            for pid, score in self.scores(features).items()
            if score >= threshold
        }


def fit(datasets: Iterable[Labelled], detector: str, model: str) -> Learned:
    x, y = training_rows(datasets, detector)
    planted = int(y.sum())
    if planted == 0 or planted == len(y):
        raise ValueError(
            f"{detector}: training needs both planted and unplanted players, "
            f"got {planted} planted of {len(y)}"
        )
    estimator = _estimator(model, y)
    estimator.fit(x, y)
    return Learned(detector=detector, model=model, estimator=estimator)


def explain(pf: PlayerFeatures, learned: Learned, score: float, threshold: float) -> str:
    """The sentence that goes on the flag."""
    who = f"A {_MODEL_LABEL[learned.model]} model trained on synthetic players"
    if learned.detector == "late_bloomer":
        return (
            f"{who} scores this player {score:.2f} as a late bloomer (it flags from "
            f"{threshold:.2f}). Height averages {pf.height_z_mean:+.1f} standard deviations "
            f"from the median for age {pf.stated_age:.0f}, and recent growth is "
            f"{pf.recent_velocity:.1f} cm/year."
        )
    growth = "growth rate unknown" if pf.velocity_z is None else f"growth rate {pf.velocity_z:+.1f}"
    output = "no output on record" if pf.output_z is None else f"output {pf.output_z:+.1f}"
    return (
        f"{who} scores this player {score:.2f} as older than the record says (it flags from "
        f"{threshold:.2f}). Against players recorded as {pf.stated_age:.0f}, in standard "
        f"deviations: height {pf.height_z_mean:+.1f}, {growth}, {output}."
    )


def rule(features: FeatureSet, detector: str) -> dict[str, str]:
    """The rule the model is compared with, unchanged."""
    if detector == "late_bloomer":
        return late_bloomer.detect(features)
    if detector == "age_fraud":
        return fraud.detect_age_misrepresentation(features)
    raise ValueError(f"unknown detector {detector!r}")


# ---------------------------------------------------------------------------
# Choosing the threshold
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Counts:
    tp: int
    fp: int
    fn: int

    @property
    def f1(self) -> float:
        return 2 * self.tp / (2 * self.tp + self.fp + self.fn) if self.tp else 0.0


Scored = tuple[dict[str, float], set[str], set[str]]  # scores, planted ids, scored population


def counts_at(scored: Iterable[Scored], threshold: float) -> Counts:
    """Pooled counts over several datasets when flagging at this threshold."""
    tp = fp = fn = 0
    for scores, truth, population in scored:
        flagged = {pid for pid, value in scores.items() if value >= threshold}
        result = score_ids("", flagged, truth, population)
        tp, fp, fn = tp + result.tp, fp + result.fp, fn + result.fn
    return Counts(tp, fp, fn)


def choose_threshold(by_threshold: dict[float, Counts], *, max_false: int | None = None) -> float | None:
    """The threshold with the highest F1, at most `max_false` wrong flags if given.

    Ties go to the higher threshold, which flags fewer players. None when no threshold keeps
    within `max_false`.
    """
    best: float | None = None
    for threshold in sorted(by_threshold):
        counts = by_threshold[threshold]
        if max_false is not None and counts.fp > max_false:
            continue
        if best is None or counts.f1 >= by_threshold[best].f1:
            best = threshold
    return best


def calibrate(train: list[Labelled], calibration: list[Labelled]) -> dict:
    """Fit on the training datasets and choose both thresholds on the calibration ones."""
    frozen: dict = {
        "note": (
            "Written by `python -m ml.challengers.learned calibrate` and committed before "
            "`report` was first run. See the docstring of ml/challengers/learned.py."
        ),
        "train_seeds": [d.seed for d in train],
        "calibration_seeds": [d.seed for d in calibration],
        "rule": {},
        "models": {},
    }
    for detector in DETECTORS:
        rule_scores = [
            score_ids("rule", rule(d.features, detector), d.truth[detector], d.population[detector])
            for d in calibration
        ]
        rule_counts = Counts(
            sum(s.tp for s in rule_scores), sum(s.fp for s in rule_scores), sum(s.fn for s in rule_scores)
        )
        frozen["rule"][detector] = {"tp": rule_counts.tp, "fp": rule_counts.fp, "fn": rule_counts.fn}
        frozen["models"][detector] = {}
        for model in MODELS:
            learned = fit(train, detector, model)
            grid = _grid(learned, calibration)
            frozen["models"][detector][model] = {
                "thresholds": {
                    "best_f1": choose_threshold(grid),
                    "no_more_flags": choose_threshold(grid, max_false=rule_counts.fp),
                },
                "grid": {f"{t:.2f}": [c.tp, c.fp, c.fn] for t, c in grid.items()},
            }
    return frozen


def _grid(learned: Learned, calibration: list[Labelled]) -> dict[float, Counts]:
    scored = [
        (learned.scores(d.features), d.truth[learned.detector], d.population[learned.detector])
        for d in calibration
    ]
    return {t: counts_at(scored, t) for t in THRESHOLDS}


def check_same_model(
    frozen: dict, learned: Learned, calibration: list[Labelled], *, strict: bool = True
) -> str | None:
    """Refuse to report a model that does not score the calibration seeds as the file says.

    With `strict=False` a difference is described and returned instead, for reproducing the
    report on another platform: XGBoost does not give bit-identical trees on every operating
    system, so a refit on Linux can move a few players across a threshold. None when the model
    is the frozen one.
    """
    expected = frozen["models"][learned.detector][learned.model]["grid"]
    found = {f"{t:.2f}": [c.tp, c.fp, c.fn] for t, c in _grid(learned, calibration).items()}
    if found == expected:
        return None
    differ = [t for t in expected if found.get(t) != expected[t]]
    largest = max(
        sum(abs(a - b) for a, b in zip(found.get(t, [0, 0, 0]), expected[t])) for t in differ
    )
    message = (
        f"{learned.detector}, {learned.model}: the refitted model scores the calibration seeds "
        f"differently from {THRESHOLDS_FILE.name} at {len(differ)} of {len(expected)} thresholds "
        f"(at most {largest} counts apart), so it is not exactly the model whose thresholds were "
        f"chosen."
    )
    if strict:
        raise RuntimeError(
            f"{message} Something changed: the code, the generator, the version of scikit-learn "
            f"or xgboost, or the operating system. Find what, rather than re-running calibrate "
            f"after the reported seeds have been seen. To reproduce on another platform anyway, "
            f"pass --allow-refit-difference; the output then says how it differs."
        )
    return message


# ---------------------------------------------------------------------------
# What drives a model
# ---------------------------------------------------------------------------


def importance(
    learned: Learned, datasets: list[Labelled], *, repeats: int = 10
) -> list[tuple[str, float, float]]:
    """How much the model's ranking gets worse when one input is shuffled, largest first.

    Permutation importance (Breiman 2001): each column of the given datasets' rows is shuffled
    in turn, `repeats` times, and the drop in average precision (how well planted cases are
    ranked above everyone else) is the column's importance. Works the same for both models.
    Returns (column, mean drop, standard deviation of the drop).
    """
    from sklearn.inspection import permutation_importance

    x, y = training_rows(datasets, learned.detector)
    result = permutation_importance(
        learned.estimator, x, y, scoring="average_precision", n_repeats=repeats, random_state=0
    )
    rows = zip(COLUMNS, result.importances_mean, result.importances_std)
    return sorted(((c, float(m), float(s)) for c, m, s in rows), key=lambda r: -r[1])


def logistic_weights(learned: Learned) -> list[tuple[str, float]]:
    """The logistic regression's weight per input, largest effect first.

    Inputs are standardised first, so a weight is the change in log odds for one standard
    deviation of that input across the training players, and weights can be compared.
    """
    if learned.model != "logistic":
        raise ValueError("only the logistic regression has weights to read")
    coefficients = learned.estimator[-1].coef_[0]
    return sorted(zip(COLUMNS, map(float, coefficients)), key=lambda r: -abs(r[1]))


# ---------------------------------------------------------------------------
# Scoring the reported seeds
# ---------------------------------------------------------------------------


def age_band(age: float) -> str:
    for low, high, label in AGE_BANDS:
        if low <= age < high:
            return label
    return "17+" if age >= AGE_BANDS[-1][1] else "under 11"


def _pooled(detector: str, scores: Iterable[Score]) -> Score:
    scores = list(scores)
    return Score(
        detector=detector,
        tp=sum(s.tp for s in scores),
        fp=sum(s.fp for s in scores),
        fn=sum(s.fn for s in scores),
        tn=sum(s.tn for s in scores),
    )


def breakdown(
    features: FeatureSet,
    flagged: Iterable[str],
    truth: set[str],
    population: set[str],
    group: Callable[[PlayerFeatures], str],
) -> dict[str, Score]:
    """Score one dataset separately inside each group of players."""
    members: dict[str, set[str]] = {}
    for pid in population:
        pf = features.players.get(pid)
        if pf is not None:
            members.setdefault(group(pf), set()).add(pid)
    flagged = set(flagged)
    return {name: score_ids(name, flagged, truth, ids) for name, ids in sorted(members.items())}


@dataclass
class Row:
    """One detector at one operating point, over every reported dataset."""

    name: str
    per_seed: list[Score] = field(default_factory=list)
    by_age: list[dict[str, Score]] = field(default_factory=list)
    by_gender: list[dict[str, Score]] = field(default_factory=list)
    by_quarter: list[fairness.QuarterAudit] = field(default_factory=list)

    def add(self, data: Labelled, detector: str, flagged: Iterable[str]) -> None:
        flagged = set(flagged)
        truth, population = data.truth[detector], data.population[detector]
        self.per_seed.append(score_ids(self.name, flagged, truth, population))
        self.by_age.append(
            breakdown(data.features, flagged, truth, population, lambda pf: age_band(pf.stated_age))
        )
        self.by_gender.append(breakdown(data.features, flagged, truth, population, lambda pf: pf.sex))
        self.by_quarter.append(fairness.audit(self.name, flagged, truth, population, data.quarters))

    @property
    def pooled(self) -> Score:
        return _pooled(self.name, self.per_seed)

    def pooled_groups(self, attribute: str) -> dict[str, Score]:
        groups: dict[str, list[Score]] = {}
        for per_dataset in getattr(self, attribute):
            for name, score in per_dataset.items():
                groups.setdefault(name, []).append(score)
        return {name: _pooled(name, scores) for name, scores in groups.items()}


def score_reported(
    frozen: dict,
    train: list[Labelled],
    calibration: list[Labelled],
    reported: list[Labelled],
    *,
    strict: bool = True,
    notes: list[str] | None = None,
) -> dict[str, list[Row]]:
    """Every detector's rule and model rows on the reported datasets.

    With `strict=False`, a model that differs from the frozen one is scored anyway and the
    difference is appended to `notes`.
    """
    rows: dict[str, list[Row]] = {}
    for detector in DETECTORS:
        rule_row = Row("rule")
        for data in reported:
            rule_row.add(data, detector, rule(data.features, detector))
        rows[detector] = [rule_row]
        for model in MODELS:
            learned = fit(train, detector, model)
            difference = check_same_model(frozen, learned, calibration, strict=strict)
            if difference and notes is not None:
                notes.append(difference)
            scores = [learned.scores(data.features) for data in reported]
            thresholds = frozen["models"][detector][model]["thresholds"]
            for point in OPERATING_POINTS:
                threshold = thresholds[point]
                if threshold is None:
                    continue
                row = Row(f"{_MODEL_LABEL[model]}, {point.replace('_', ' ')} (from {threshold:.2f})")
                for data, scored in zip(reported, scores):
                    row.add(data, detector, (pid for pid, s in scored.items() if s >= threshold))
                rows[detector].append(row)
    return rows


def gain_interval(
    row: Row, rule_row: Row, *, draws: int = 2000, seed: int = 0
) -> tuple[tuple[float, float], tuple[float, float]]:
    """95% intervals on the gain over the rule: pooled F1, and false flags (negative is fewer).

    The datasets are resampled with replacement, not the players, because the split is by
    dataset and the players in one dataset share its cohort reference. Both rows are scored on
    the same resampled datasets each time, so the interval is on the paired difference.
    """
    rng = random.Random(seed)
    n = len(row.per_seed)
    f1_gains, flag_gains = [], []
    for _ in range(draws):
        picks = [rng.randrange(n) for _ in range(n)]
        mine = _pooled("", (row.per_seed[i] for i in picks))
        theirs = _pooled("", (rule_row.per_seed[i] for i in picks))
        f1_gains.append(mine.f1 - theirs.f1)
        flag_gains.append(mine.fp - theirs.fp)
    low, high = int(0.025 * draws), int(0.975 * draws) - 1
    f1_gains.sort()
    flag_gains.sort()
    return (f1_gains[low], f1_gains[high]), (flag_gains[low], flag_gains[high])


def _compare(row: Row, rule_row: Row) -> str:
    won = lost = 0
    for mine, theirs in zip(row.per_seed, rule_row.per_seed):
        if mine.f1 > theirs.f1:
            won += 1
        elif mine.f1 < theirs.f1:
            lost += 1
    return f"{won} / {lost} / {len(row.per_seed) - won - lost}"


def render(rows: dict[str, list[Row]], title: str, notes: list[str] | None = None) -> str:
    """Markdown tables, in the shape the README's challenger sections use."""
    out = [f"# {title}", ""]
    for note in notes or []:
        out += [f"**Not the frozen model.** {note}", ""]
    for detector, detector_rows in rows.items():
        rule_row = detector_rows[0]
        planted = rule_row.pooled.support
        out += [
            f"## {_DETECTOR_LABEL[detector]}: {len(rule_row.per_seed)} datasets, "
            f"{planted} planted cases",
            "",
            "| | caught | false flags | precision | recall | F1 | mean F1 per dataset "
            "| datasets won / lost / tied against the rule "
            "| F1 gain, 95% interval | false flags gained, 95% interval |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for row in detector_rows:
            pooled = row.pooled
            mean_f1 = sum(s.f1 for s in row.per_seed) / len(row.per_seed) if row.per_seed else 0.0
            versus = f1_gain = flag_gain = ""
            if row is not rule_row and row.per_seed:
                versus = _compare(row, rule_row)
                (f1_low, f1_high), (fp_low, fp_high) = gain_interval(row, rule_row)
                f1_gain = f"{f1_low:+.3f} to {f1_high:+.3f}"
                flag_gain = f"{fp_low:+.0f} to {fp_high:+.0f}"
            out.append(
                f"| {row.name} | {pooled.tp} | {pooled.fp} | {pooled.precision:.3f} "
                f"| {pooled.recall:.3f} | {pooled.f1:.3f} | {mean_f1:.3f} | {versus} "
                f"| {f1_gain} | {flag_gain} |"
            )
        for attribute, heading in (("by_age", "stated age"), ("by_gender", "gender")):
            groups = sorted({name for row in detector_rows for name in row.pooled_groups(attribute)})
            out += [
                "",
                f"By {heading}: caught of planted, then false flags",
                "",
                "| | " + " | ".join(groups) + " |",
                "| --- |" + " --- |" * len(groups),
            ]
            for row in detector_rows:
                pooled = row.pooled_groups(attribute)
                caught = [
                    f"{pooled[g].tp}/{pooled[g].support}" if g in pooled else "-" for g in groups
                ]
                false = [str(pooled[g].fp) if g in pooled else "-" for g in groups]
                out.append(f"| {row.name}, caught | " + " | ".join(caught) + " |")
                out.append(f"| {row.name}, false flags | " + " | ".join(false) + " |")
        out.append(
            fairness.render(
                [fairness.pool(row.by_quarter) for row in detector_rows],
                f"{_DETECTOR_LABEL[detector]}, by birth quarter (relative age), pooled",
            )
        )
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def generate(seeds: Iterable[int], directory: Path) -> list[Labelled]:
    """Generate one dataset per seed, the same way `ml.run_eval --seed-sweep` does."""
    from ml.run_eval import _generate

    datasets = []
    for seed in seeds:
        out = directory / str(seed)
        print(f"generating seed {seed} ...", file=sys.stderr)
        _generate(seed, out)
        truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
        datasets.append(labelled(FeatureSet(out), truth, seed))
    return datasets


def main(argv: list[str] | None = None) -> int:
    import argparse
    import tempfile

    from ml import challengers

    parser = argparse.ArgumentParser(prog="learned", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    cal = commands.add_parser("calibrate", help="fit on the training seeds, choose thresholds")
    cal.add_argument("--train-seeds", type=int, nargs="+", default=list(TRAIN_SEEDS))
    cal.add_argument("--calibration-seeds", type=int, nargs="+", default=list(CALIBRATION_SEEDS))
    cal.add_argument("--out", type=Path, default=THRESHOLDS_FILE)
    rep = commands.add_parser("report", help="score the reported seeds with the frozen thresholds")
    rep.add_argument("--thresholds", type=Path, default=THRESHOLDS_FILE)
    rep.add_argument("--seeds", type=int, nargs="+", default=list(REPORTED_SEEDS))
    rep.add_argument("--performance-follows-maturity", action="store_true")
    rep.add_argument("--json", type=Path, default=None, help="also write the counts as JSON")
    exp = commands.add_parser("explain", help="what drives each model, on the calibration seeds")
    exp.add_argument("--thresholds", type=Path, default=THRESHOLDS_FILE)
    for command in (rep, exp):
        command.add_argument(
            "--allow-refit-difference",
            action="store_true",
            help="run even if a refitted model does not reproduce the frozen calibration counts "
            "(another operating system); the output says how it differs",
        )
    args = parser.parse_args(argv)

    if not challengers.available():
        print("Needs scikit-learn and xgboost: pip install -r ml/requirements.txt", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="northstar-learned-") as tmp:
        if args.command == "calibrate":
            check_seeds(args.train_seeds, args.calibration_seeds, REPORTED_SEEDS)
            train = generate(args.train_seeds, Path(tmp))
            calibration = generate(args.calibration_seeds, Path(tmp))
            frozen = calibrate(train, calibration)
            args.out.write_text(json.dumps(frozen, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({d: frozen["rule"][d] for d in DETECTORS}, indent=2))
            for detector in DETECTORS:
                for model in MODELS:
                    chosen = frozen["models"][detector][model]["thresholds"]
                    print(f"{detector}, {model}: {chosen}")
            print(f"wrote {args.out}")
            return 0

        if not args.thresholds.exists():
            print(f"No thresholds at {args.thresholds}. Run calibrate first.", file=sys.stderr)
            return 1
        frozen = json.loads(args.thresholds.read_text(encoding="utf-8"))
        reported_seeds = REPORTED_SEEDS if args.command == "explain" else args.seeds
        check_seeds(frozen["train_seeds"], frozen["calibration_seeds"], reported_seeds)
        train = generate(frozen["train_seeds"], Path(tmp))
        calibration = generate(frozen["calibration_seeds"], Path(tmp))

        strict = not args.allow_refit_difference
        if args.command == "explain":
            for detector in DETECTORS:
                for model in MODELS:
                    learned = fit(train, detector, model)
                    difference = check_same_model(frozen, learned, calibration, strict=strict)
                    print(f"\n{_DETECTOR_LABEL[detector]}, {_MODEL_LABEL[model]}")
                    if difference:
                        print(f"  Not the frozen model. {difference}")
                    print("  permutation importance on the calibration seeds (drop in average precision):")
                    for column, mean, spread in importance(learned, calibration):
                        print(f"    {column:24} {mean:+.3f}  (sd {spread:.3f})")
                    if model == "logistic":
                        print("  weights, per standard deviation of the input (log odds):")
                        for column, weight in logistic_weights(learned):
                            print(f"    {column:24} {weight:+.2f}")
            return 0

        from data.pipelines.synthetic import players

        world = "ordinary world"
        before = players.PERFORMANCE_FOLLOWS_MATURITY
        if args.performance_follows_maturity:
            players.PERFORMANCE_FOLLOWS_MATURITY = True
            world = "what-if: performance follows maturity"
        try:
            reported = generate(args.seeds, Path(tmp))
        finally:
            players.PERFORMANCE_FOLLOWS_MATURITY = before

        notes: list[str] = []
        rows = score_reported(frozen, train, calibration, reported, strict=strict, notes=notes)
        print(render(rows, f"Learned detectors against the rules, {world}", notes))
        if args.json:
            payload: dict = {"not_the_frozen_model": notes} if notes else {}
            payload |= {
                detector: {
                    row.name: {
                        "pooled": row.pooled.as_dict(),
                        "per_dataset": [s.as_dict() for s in row.per_seed],
                        "by_age": {k: v.as_dict() for k, v in row.pooled_groups("by_age").items()},
                        "by_gender": {
                            k: v.as_dict() for k, v in row.pooled_groups("by_gender").items()
                        },
                    }
                    for row in detector_rows
                }
                for detector, detector_rows in rows.items()
            }
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
