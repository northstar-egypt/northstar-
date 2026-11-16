"""Three expected-goals models, simplest first, and how they are scored.

- **baseline**: logistic regression on distance and goal angle only. Any model has to beat it.
- **logistic**: logistic regression on every feature in `features.py`, standardised.
- **boosted**: gradient-boosted trees (XGBoost) on the same features.

Settings are chosen on the training leagues alone, by cross-validation that keeps each match's
shots in one fold (shots from one match are not independent). The held-out tournaments are
scored once, after everything is fixed.
"""

from __future__ import annotations

import random

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from ml.xg import features as feats

LOGISTIC_C = (0.01, 0.1, 1.0)
BOOSTED = (
    {"max_depth": 3, "n_estimators": 300, "learning_rate": 0.05},
    {"max_depth": 4, "n_estimators": 300, "learning_rate": 0.05},
    {"max_depth": 3, "n_estimators": 600, "learning_rate": 0.03},
)
FOLDS = 5
# Two threads: this runs on a laptop someone is using.
THREADS = 2


def matrix(rows: list[dict], kind: str) -> np.ndarray:
    if kind == "baseline":
        return np.array([[r["features"]["distance"], r["features"]["angle"]] for r in rows])
    return np.array([feats.vector(r["features"]) for r in rows])


def build(kind: str, setting=None):
    if kind == "boosted":
        return XGBClassifier(objective="binary:logistic", subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
                             n_jobs=THREADS, random_state=0, eval_metric="logloss", **(setting or BOOSTED[0]))
    c = setting if setting is not None else 1.0
    return make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=2000))


def cross_validated(kind: str, setting, rows: list[dict]) -> float:
    """Mean log loss over grouped folds of the training rows."""
    x, y, groups = matrix(rows, kind), np.array([r["goal"] for r in rows]), np.array([r["match"] for r in rows])
    losses = []
    for fit_idx, val_idx in GroupKFold(n_splits=FOLDS).split(x, y, groups):
        model = build(kind, setting).fit(x[fit_idx], y[fit_idx])
        losses.append(log_loss(y[val_idx], model.predict_proba(x[val_idx])[:, 1], labels=[0, 1]))
    return float(np.mean(losses))


def choose(kind: str, rows: list[dict]) -> tuple[object, dict[str, float]]:
    """The setting with the lowest cross-validated log loss, and every setting's score."""
    options = {"baseline": [None], "logistic": list(LOGISTIC_C), "boosted": list(BOOSTED)}[kind]
    scores = {str(o): cross_validated(kind, o, rows) for o in options}
    best = min(options, key=lambda o: scores[str(o)])
    return best, scores


def fit(kind: str, setting, rows: list[dict]):
    return build(kind, setting).fit(matrix(rows, kind), np.array([r["goal"] for r in rows]))


def calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error over equal-count bins: how far, on average, predicted xG sits
    from the share that went in."""
    order = np.argsort(p)
    total = 0.0
    for chunk in np.array_split(order, bins):
        if len(chunk):
            total += len(chunk) * abs(p[chunk].mean() - y[chunk].mean())
    return total / len(p)


def scores(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {
        "log_loss": log_loss(y, p, labels=[0, 1]), "brier": brier_score_loss(y, p), "auc": roc_auc_score(y, p),
        "calibration": calibration_error(y, p), "xg_total": float(p.sum()), "goals": int(y.sum()),
    }


def bootstrap_difference(rows: list[dict], p_a: np.ndarray, p_b: np.ndarray, rounds: int = 1000,
                         seed: int = 0) -> tuple[float, float, float]:
    """Log loss of A minus log loss of B, with a 95% interval from resampling whole matches."""
    y = np.array([r["goal"] for r in rows])
    eps = 1e-6

    def per_shot(p):
        p = np.clip(p, eps, 1 - eps)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p))

    diff = per_shot(p_a) - per_shot(p_b)
    by_match: dict[int, list[int]] = {}
    for i, r in enumerate(rows):
        by_match.setdefault(r["match"], []).append(i)
    matches = list(by_match)
    rng = random.Random(seed)
    draws = []
    for _ in range(rounds):
        idx = [i for m in (rng.choice(matches) for _ in matches) for i in by_match[m]]
        draws.append(float(diff[idx].mean()))
    draws.sort()
    return float(diff.mean()), draws[int(0.025 * rounds)], draws[int(0.975 * rounds) - 1]




# The setting the published evaluation chose (ml/README.md, "Expected goals"): fixed here, so
# the app uses exactly the model that was graded, not one re-chosen on every load.
CHOSEN = BOOSTED[2]


def predict_for_app(train: list[dict], others: list[dict], folds: int = FOLDS) -> dict[str, float]:
    """xG for every shot, by event id, for the app (data/pipelines/statsbomb/load.py).

    Shots in the training leagues get out-of-fold predictions: each match's shots are scored by
    a model fitted without that match, so a training player's xG is not flattered by a model
    that saw their shots. Every other shot is scored by the model fitted on all of `train`."""
    out: dict[str, float] = {}
    if train:
        x, y = matrix(train, "boosted"), np.array([r["goal"] for r in train])
        groups = np.array([r["match"] for r in train])
        for fit_idx, held_idx in GroupKFold(n_splits=folds).split(x, y, groups):
            fold = build("boosted", CHOSEN).fit(x[fit_idx], y[fit_idx])
            for i, p in zip(held_idx, fold.predict_proba(x[held_idx])[:, 1]):
                out[train[i]["id"]] = float(p)
    if others:
        full = build("boosted", CHOSEN).fit(matrix(train, "boosted"), np.array([r["goal"] for r in train]))
        for r, p in zip(others, full.predict_proba(matrix(others, "boosted"))[:, 1]):
            out[r["id"]] = float(p)
    return out
