"""The height forecast on the player profile, from the graded model in `ml/forecasting`.

This file does not contain a model. It runs the same code that `python -m ml.run_forecast_eval`
scores, on the rows in this database, so the forecast a coach sees is the forecast whose error
is published in `ml/README.md`, not a look-alike.

What is shown, and why
----------------------
- **Under 18:** cohort velocity. The last reading plus the growth the median child of that sex
  does between the two ages. It beat both graded baselines on every seed (0.86 cm against
  3.19 cm for last value).
- **18 and over:** a flat line at the last reading. Growth has finished, and the evaluation
  showed cohort velocity wrongly keeps adults growing (0.91 cm against 0.64 cm for last value).

Every point carries an **80% band**, learned the walk-forward way: from the errors of earlier
forecasts on this database whose outcome had already been measured, per horizon (0 to 3, 3 to
6, 6 to 12 months), per group (under 18 or adult) and **per gender**. Girls are few (table
tennis only) and their growth curve is learned from few children, so their forecasts are less
accurate; a band pooled with the boys' would be far too narrow for them. The note on the
profile states how often past readings fell inside the band for that player's own gender. The
band is the forecast's honest content; the centre line alone would claim a confidence the
model does not have.

When there is no forecast
-------------------------
Nothing is drawn, and the profile says why, when the player has no date of birth or sex, fewer
than two height readings (the evaluation's own rule), a last reading more than a year ago (the
model was never checked that far out), or when the database holds too few past forecasts to
learn a band from (fewer than 30 in a horizon).

Cached per process for `_TTL_SECONDS`, like the cohort reference: rebuilding takes about half
a second over the synthetic dataset, and a band does not move when one child is measured.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import PlayerStatus
from app.models.measurement import Measurement
from app.models.player import Player


def _make_ml_importable() -> None:
    """`ml/` sits at the repository root, beside `apps/`. The API image puts it on the path
    (see apps/api/Dockerfile); a local run from apps/api finds it by walking up."""
    try:
        import ml.forecasting  # noqa: F401
    except ImportError:
        for parent in Path(__file__).resolve().parents:
            if (parent / "ml" / "forecasting" / "models.py").is_file():
                sys.path.insert(0, str(parent))
                return


_make_ml_importable()

from ml.forecasting.models import (  # noqa: E402
    PlayerHistory,
    Snapshot,
    age_at,
    cohort_velocity,
    last_value,
)
from ml.forecasting.walk_forward import (  # noqa: E402
    INTERVAL_COVERAGE,
    MIN_INTERVAL_HISTORY,
    MIN_READINGS,
    build_cases,
    horizon_band,
    quantile,
)

_TAIL = (1 - INTERVAL_COVERAGE) / 2

YOUTH_MODEL = "cohort velocity"
ADULT_MODEL = "baseline: last value"
ADULT_AGE = 18

# The horizons drawn on the profile: the end of each band the evaluation scores.
HORIZONS_DAYS = (91, 182, 365)
# A last reading older than this is further out than the model was ever checked.
MAX_STALENESS_DAYS = 365

_TTL_SECONDS = 300


@dataclass
class _Model:
    built_at: float = 0.0
    snapshot: Snapshot | None = None
    histories: dict[str, PlayerHistory] = field(default_factory=dict)
    # (group, gender, horizon band) -> errors (actual minus predicted) of past forecasts, cm.
    errors: dict[tuple[str, str, str], list[float]] = field(default_factory=dict)
    # (group, gender) -> [readings inside the band, forecasts that had a band], walk-forward.
    coverage: dict[tuple[str, str], list[int]] = field(default_factory=dict)


_model = _Model()
_lock = threading.Lock()


def _histories(db: Session) -> dict[str, PlayerHistory]:
    players = db.execute(
        select(Player.id, Player.sex, Player.date_of_birth)
        .where(Player.status != PlayerStatus.MERGED.value)
        .where(Player.date_of_birth.is_not(None))
    ).all()
    histories = {
        str(pid): PlayerHistory(str(pid), sex or "unknown", dob, []) for pid, sex, dob in players
    }
    rows = db.execute(
        select(Measurement.player_id, Measurement.measured_at, Measurement.value)
        .where(Measurement.metric == "height_cm")
        .where(Measurement.value.is_not(None))
    ).all()
    for pid, measured_at, value in rows:
        history = histories.get(str(pid))
        if history is not None:
            history.heights.append((measured_at, float(value)))
    for history in histories.values():
        history.heights.sort()
    return histories


def _group(stated_age: float) -> str:
    return "youth" if stated_age < ADULT_AGE else "adult"


def _build(db: Session, today: date) -> _Model:
    histories = _histories(db)
    model = _Model(built_at=time.time(), histories=histories)
    model.snapshot = Snapshot(today, histories)

    _, cases = build_cases(histories)

    def key(case) -> tuple[str, str, str]:
        return (_group(case.stated_age), case.sex, horizon_band(case.horizon_days))

    def predicted(case) -> float | None:
        return case.predictions.get(
            YOUTH_MODEL if _group(case.stated_age) == "youth" else ADULT_MODEL
        )

    # Coverage, checked the way the evaluation checks it: at each origin, the band comes only
    # from forecasts whose outcome had already been measured by then, for the same group,
    # gender and horizon. Calibrating on the future would make the check meaningless.
    for origin in sorted({case.origin for case in cases}):
        past: dict[tuple[str, str, str], list[float]] = {}
        for case in cases:
            value = predicted(case)
            if case.target <= origin and value is not None:
                past.setdefault(key(case), []).append(case.actual - value)
        for case in cases:
            value = predicted(case)
            errors = past.get(key(case), [])
            if case.origin != origin or value is None or len(errors) < MIN_INTERVAL_HISTORY:
                continue
            low = value + quantile(errors, _TAIL)
            high = value + quantile(errors, 1 - _TAIL)
            tally = model.coverage.setdefault(key(case)[:2], [0, 0])
            tally[0] += low <= case.actual <= high
            tally[1] += 1

    # The band shown today learns from every past forecast whose outcome is known.
    for case in cases:
        value = predicted(case)
        if value is not None:
            model.errors.setdefault(key(case), []).append(case.actual - value)
    return model


def _get_model(db: Session, today: date) -> _Model:
    global _model
    with _lock:
        stale = (time.time() - _model.built_at) > _TTL_SECONDS
        if stale or _model.snapshot is None or _model.snapshot.origin != today:
            _model = _build(db, today)
        return _model


def reset_cache() -> None:
    """Drop the cached model. Used by tests, which change the data underneath it."""
    global _model
    with _lock:
        _model = _Model()


@dataclass
class Forecast:
    points: list[dict]
    # The date the forecast is made from, so the chart can mark "today" correctly even when
    # the last measurement was months ago.
    origin: date | None
    # One or two sentences for the screen: which model, how its band was checked, or why
    # there is no forecast at all.
    note: str


def forecast_height(db: Session, player: Player, *, today: date | None = None) -> Forecast:
    today = today or date.today()
    if player.date_of_birth is None or player.sex is None:
        return Forecast([], None, "No forecast: the date of birth or sex is not recorded.")

    model = _get_model(db, today)
    history = model.histories.get(str(player.id))
    if history is None or len(history.heights) < MIN_READINGS:
        return Forecast(
            [], None, "No forecast yet: it needs at least two height measurements."
        )

    last_date = history.heights[-1][0]
    if (today - last_date).days > MAX_STALENESS_DAYS:
        return Forecast(
            [],
            None,
            "No forecast: the last height was measured more than a year ago, further out "
            "than the model has been checked. Measure again to get one.",
        )

    group = _group(age_at(history.dob, today))
    forecaster = cohort_velocity if group == "youth" else last_value

    points: list[dict] = []
    for days in HORIZONS_DAYS:
        errors = model.errors.get((group, history.sex, horizon_band(days)), [])
        if len(errors) < MIN_INTERVAL_HISTORY:
            # A band from a handful of cases is not a band. Stop rather than draw one.
            break
        target = today + timedelta(days=days)
        centre = forecaster(model.snapshot, history, target)
        if centre is None:
            break
        points.append(
            {
                "date": target,
                "value": round(centre, 1),
                "lower": round(centre + quantile(errors, _TAIL), 1),
                "upper": round(centre + quantile(errors, 1 - _TAIL), 1),
            }
        )

    if not points:
        return Forecast(
            [],
            None,
            "No forecast: the database does not yet hold enough past forecasts for players "
            "like this one (same age group and gender) to learn an honest uncertainty band "
            "from.",
        )

    coverage = f"{INTERVAL_COVERAGE:.0%}"
    who = {"male": "boys", "female": "girls"}.get(history.sex, "players")
    hits, banded = model.coverage.get((group, history.sex), [0, 0])
    if group == "youth":
        checked = (
            f" Checked against this database, {hits / banded:.0%} of past readings for {who} "
            f"fell inside the band."
            if banded
            else ""
        )
        note = (
            f"Cohort velocity: the last measurement plus the growth typical for their age and "
            f"sex. The shaded area is where {coverage} of readings should fall.{checked}"
        )
    else:
        note = (
            f"Adult: growth has finished, so the forecast is flat at the last measurement. The "
            f"shaded area is where {coverage} of readings should fall, which is mostly "
            f"measurement error."
        )
    return Forecast(points, today, note)
