"""XGBoost challenger for the height forecast.

What it learns
--------------
The change in height between a player's last reading and a later date, from eight numbers
known at the last reading:

  gender, age at the last reading, horizon in years, the last height, the player's own recent
  growth rate, how far they sit from the median height for their age (z score), the growth
  the cohort curve expects over the horizon (cohort velocity's own answer), and how many
  readings they have.

So it can learn everything cohort velocity knows, plus when to trust the player's own rate
over the cohort's, which is exactly what a late bloomer needs.

No lookahead, by construction
-----------------------------
A forecaster here is handed a `Snapshot`: every reading on or before the origin date, for
every player, and nothing later. The model is trained **inside that snapshot**: for each
player, every earlier reading is treated as a "last reading" and every later reading (still on
or before the origin) as a target. It never sees a reading after the origin, so it is
walk-forward in exactly the same way as the v1 models, and the same no-lookahead test covers
it (`ml/tests/test_challengers.py`). One model is trained per snapshot and reused for every
forecast made at that origin.

Hyperparameters, fixed before the first run and never changed: 300 trees of depth 4, learning
rate 0.05, row and column subsampling 0.8, at least 5 rows per leaf. Standard, conservative
defaults for a few thousand tabular rows.
"""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import xgboost as xgb

from ml.forecasting.models import (
    DAYS_PER_YEAR,
    MIN_VELOCITY_GAP_DAYS,
    PlayerHistory,
    Snapshot,
    age_at,
)

NAME = "challenger: xgboost"

PARAMS = dict(
    n_estimators=300,
    max_depth=4,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=5,
    reg_lambda=1.0,
    tree_method="hist",
    random_state=0,
    n_jobs=1,
)

# Training pairs further apart than this are not like anything the model is asked. Forecasts
# go a year past the origin, and the last reading can sit some months before the origin.
MAX_PAIR_DAYS = 730
# With fewer training rows than this the model declines, counted as missing, never guessed.
MIN_TRAINING_ROWS = 200


def _own_velocity(readings: list[tuple[date, float]]) -> float:
    """cm per year from the last reading back to the latest one at least 150 days earlier."""
    last_when, last_cm = readings[-1]
    for when, cm in reversed(readings[:-1]):
        gap = (last_when - when).days
        if gap >= MIN_VELOCITY_GAP_DAYS:
            return (last_cm - cm) / (gap / DAYS_PER_YEAR)
    return math.nan


def _features(
    snapshot: Snapshot, sex: str, dob: date, readings: list[tuple[date, float]], target: date
) -> list[float]:
    when, cm = readings[-1]
    age_now = age_at(dob, when)
    age_then = age_at(dob, target)
    point = snapshot.height_curve.at(sex, age_now)
    z = (cm - point[0]) / point[1] if point else math.nan
    return [
        1.0 if sex == "female" else 0.0,
        age_now,
        age_then - age_now,
        cm,
        _own_velocity(readings),
        z,
        snapshot.growth_between(sex, age_now, age_then),
        float(len(readings)),
    ]


def _train(snapshot: Snapshot) -> xgb.XGBRegressor | None:
    rows: list[list[float]] = []
    targets: list[float] = []
    for history in snapshot.players.values():
        heights = history.heights
        for k in range(1, len(heights)):
            last_when, last_cm = heights[k]
            for when, cm in heights[k + 1 :]:
                if (when - last_when).days > MAX_PAIR_DAYS:
                    break
                rows.append(_features(snapshot, history.sex, history.dob, heights[: k + 1], when))
                targets.append(cm - last_cm)
    if len(rows) < MIN_TRAINING_ROWS:
        return None
    model = xgb.XGBRegressor(**PARAMS)
    model.fit(np.asarray(rows, dtype=float), np.asarray(targets, dtype=float))
    return model


# One model per snapshot. The snapshot object itself is held, so its id cannot be reused by a
# later snapshot while the cache still points at it.
_cache: tuple[Snapshot, xgb.XGBRegressor | None] | None = None


def _model_for(snapshot: Snapshot) -> xgb.XGBRegressor | None:
    global _cache
    if _cache is None or _cache[0] is not snapshot:
        _cache = (snapshot, _train(snapshot))
    return _cache[1]


def xgboost_forecast(
    snapshot: Snapshot, history: PlayerHistory, target: date
) -> float | None:
    """Same signature as the v1 forecasters in ml/forecasting/models.py."""
    if len(history.heights) < 2:
        return None
    model = _model_for(snapshot)
    if model is None:
        return None
    x = np.asarray([_features(snapshot, history.sex, history.dob, history.heights, target)])
    return history.heights[-1][1] + float(model.predict(x)[0])


FORECASTERS = {NAME: xgboost_forecast}
