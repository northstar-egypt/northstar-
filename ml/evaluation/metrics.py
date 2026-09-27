"""Precision, recall and F1 for a set of predicted player ids.

The three detectors are scored against a *closed-world* answer key: every player
id in the population that a label set does not list is a true negative for that
detector. `data/pipelines/synthetic/ground_truth.py` says so explicitly, and it
matters, because the difference between "not a positive" and "unlabelled" is the
difference between a real recall number and a meaningless one.

Set arithmetic rather than aligned vectors
------------------------------------------
A detector here returns the ids it thinks are positive. Scoring is then four set
operations against the label set and the population, which is both easier to read
and harder to get subtly wrong than keeping two parallel arrays in the same
order. `ground_truth.label_vectors()` still exists for anything that wants the
sklearn-shaped interface.

Intervals
---------
The positive classes are small: 14 late bloomers, 14 fraud cases, 24 duplicate
records in a population of 212. A recall of 0.71 is 10 of 14, and one case moving
either way shifts it by 7 points. Reporting a bare F1 to three decimals from a
sample that size implies a precision the number does not have, so every rate
carries a Wilson score interval and every table carries the raw counts it was
computed from.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion.

    Wilson rather than the normal approximation because the normal one is badly
    behaved exactly where we are: small n, and proportions near 0 or 1, where it
    happily reports bounds below zero or above one.
    """
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


@dataclass(frozen=True)
class Score:
    """One detector's result on one dataset."""

    detector: str
    tp: int
    fp: int
    fn: int
    tn: int
    # Ids kept for error analysis. A list of which cases were missed is worth more
    # than the F1 that summarises them.
    false_negatives: tuple[str, ...] = ()
    false_positives: tuple[str, ...] = ()
    note: str = ""

    @property
    def predicted(self) -> int:
        return self.tp + self.fp

    @property
    def support(self) -> int:
        """Number of true positives in the answer key."""
        return self.tp + self.fn

    @property
    def population(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def prevalence(self) -> float:
        return self.support / self.population if self.population else 0.0

    @property
    def precision(self) -> float:
        # A detector that predicts nothing has undefined precision. Reporting 0.0
        # is the honest reading here: it found none of them, and pairing it with
        # `predicted == 0` in the table stops it being mistaken for a bad model
        # rather than an empty one.
        return self.tp / self.predicted if self.predicted else 0.0

    @property
    def recall(self) -> float:
        return self.tp / self.support if self.support else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def precision_ci(self) -> tuple[float, float]:
        return wilson_interval(self.tp, self.predicted)

    @property
    def recall_ci(self) -> tuple[float, float]:
        return wilson_interval(self.tp, self.support)

    def as_dict(self) -> dict:
        return {
            "detector": self.detector,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "tn": self.tn,
            "support": self.support,
            "predicted": self.predicted,
            "population": self.population,
            "prevalence": round(self.prevalence, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "precision_ci95": [round(v, 4) for v in self.precision_ci],
            "recall_ci95": [round(v, 4) for v in self.recall_ci],
            "false_negatives": list(self.false_negatives),
            "false_positives": list(self.false_positives),
            "note": self.note,
        }


def score_ids(
    detector: str,
    predicted: set[str] | list[str],
    truth: set[str] | list[str],
    population: set[str] | list[str],
    *,
    note: str = "",
) -> Score:
    """Score a set of predicted ids against the answer key.

    Anything predicted that is not in the population is dropped rather than
    counted. A detector inventing ids is a bug in the detector, and silently
    letting them inflate the false-positive count would hide it behind a merely
    disappointing precision number.
    """
    population = set(population)
    predicted = set(predicted) & population
    truth = set(truth) & population

    tp = predicted & truth
    fp = predicted - truth
    fn = truth - predicted
    tn = population - predicted - truth

    return Score(
        detector=detector,
        tp=len(tp),
        fp=len(fp),
        fn=len(fn),
        tn=len(tn),
        false_negatives=tuple(sorted(fn)),
        false_positives=tuple(sorted(fp)),
        note=note,
    )


@dataclass
class ScoreSet:
    """Several scores that belong in one table, for example a detector and its baselines."""

    title: str
    scores: list[Score] = field(default_factory=list)

    def add(self, score: Score) -> Score:
        self.scores.append(score)
        return score

    def as_dict(self) -> dict:
        return {"title": self.title, "scores": [s.as_dict() for s in self.scores]}


# ---------------------------------------------------------------------------
# Forecast error
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ErrorScore:
    """One forecaster's error over a set of forecast cases.

    `bias` is mean(predicted - actual), so positive means the forecaster runs tall. MAE and
    RMSE say how wrong it is; bias says which way, and a model that is systematically short
    for late maturers is a different finding from one that is merely noisy.

    `missing` counts cases the forecaster declined to answer. They are excluded from the
    errors rather than filled in, and reported so a model cannot look accurate by staying
    quiet on the hard cases.
    """

    forecaster: str
    n: int
    mae: float
    rmse: float
    bias: float
    missing: int = 0
    # 95% interval on MAE from resampling players, not forecast cases. See `error_score`.
    mae_ci: tuple[float, float] = (0.0, 0.0)
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "forecaster": self.forecaster,
            "n": self.n,
            "mae": round(self.mae, 4),
            "rmse": round(self.rmse, 4),
            "bias": round(self.bias, 4),
            "missing": self.missing,
            "mae_ci95": [round(v, 4) for v in self.mae_ci],
            "note": self.note,
        }


def error_score(
    forecaster: str,
    pairs: list[tuple[str, float | None, float]],
    *,
    resamples: int = 1000,
    seed: int = 0,
    note: str = "",
) -> ErrorScore:
    """Score (player_id, predicted, actual) triples.

    The interval resamples *players*, not cases. One player contributes a forecast from
    every origin to every later reading, so their cases are strongly correlated, and treating
    two thousand cases from two hundred children as two thousand independent draws would
    report an interval several times too narrow.
    """
    import random

    answered = [(pid, p, a) for pid, p, a in pairs if p is not None]
    missing = len(pairs) - len(answered)
    if not answered:
        return ErrorScore(forecaster, 0, 0.0, 0.0, 0.0, missing=missing, note=note)

    errors = [p - a for _, p, a in answered]
    n = len(errors)
    mae = sum(abs(e) for e in errors) / n
    rmse = math.sqrt(sum(e * e for e in errors) / n)
    bias = sum(errors) / n

    by_player: dict[str, list[float]] = {}
    for pid, p, a in answered:
        by_player.setdefault(pid, []).append(abs(p - a))
    players = sorted(by_player)
    rng = random.Random(seed)
    maes = []
    for _ in range(resamples):
        total = count = 0.0
        for pid in rng.choices(players, k=len(players)):
            total += sum(by_player[pid])
            count += len(by_player[pid])
        maes.append(total / count)
    maes.sort()
    ci = (maes[int(0.025 * resamples)], maes[int(0.975 * resamples) - 1])

    return ErrorScore(forecaster, n, mae, rmse, bias, missing=missing, mae_ci=ci, note=note)
