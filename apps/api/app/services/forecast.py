"""The height forecast on the player profile, from the graded model the evaluation picked.

This file does not contain a model. It runs the same code that `python -m ml.run_forecast_eval`
scores, on the rows in this database, so the forecast a coach sees is the forecast whose error
is published in `ml/README.md`, not a look-alike.

What is shown, and why
----------------------
- **Under 18:** XGBoost (`ml/challengers/xgb_forecast.py`). It learns the change in height
  from the last reading, the child's own recent growth rate, where they sit against the
  median for their age, and the growth the cohort curve expects. It beat cohort velocity on
  every seed (0.80 cm against 0.86), and by most on the hard cases: girls 1.25 against 2.26,
  late bloomers 1.04 against 1.20.
- **18 and over:** a flat line at the last reading. Growth has finished, and last value is
  still the best model for adults (0.64 cm, against 0.68 for XGBoost).

Every point carries an **80% band**, learned the walk-forward way from the errors of earlier
XGBoost forecasts on this database whose outcome had already been measured, per horizon (0 to
3, 3 to 6, 6 to 12 months), per group (under 18 or adult) and **per gender**. Girls are few
(table tennis only), so a band pooled with the boys' would be too narrow for them. The note on
the profile states how often past readings for that player's own gender fell inside the band.
The band is the forecast's honest content; the centre line alone would claim a confidence the
model does not have.

Analytics consent
-----------------
A player whose guardian has withdrawn analytics consent gets no forecast, and their readings
are left out of the model everyone else's forecast learns from: training on their heights is
still using their data for analytics. The same rule as the table tennis rating (rating.py).

When there is no forecast
-------------------------
Nothing is drawn, and the profile says why, when analytics consent is not in effect, when the
player has no date of birth or sex, fewer than two height readings (the evaluation's own rule),
a last reading more than a year ago (the model was never checked that far out), when the
database holds too few past forecasts to learn a band from (fewer than 30 in a horizon), or too
few readings to train XGBoost at all.

Caching
-------
Building the model means a full walk-forward run with an XGBoost fit at every origin: about
four seconds on the synthetic dataset on a laptop, nine inside the API container. So the API
builds it in the background as it starts (`warm_up`, called from app/main.py), and when the
model is more than `_TTL_SECONDS` old, or was built on an earlier day, one background thread
rebuilds it while requests keep using the previous one. A request waits only when there is no
model at all, for example one that arrives within seconds of the API starting.
The player's own readings are always read fresh, so a height a coach has just logged moves
that player's forecast at once; only the population the model learned from lags. A consent
change does not wait for the TTL: each request compares a cheap signature of the consent table
with the one the model was built on, and a difference starts the rebuild at once. The player
whose consent was withdrawn loses their forecast on the next request, since their own consent
is always checked fresh; the others' models stop using their readings once the rebuild lands,
seconds later.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ConsentPurpose, PlayerStatus
from app.models.measurement import Measurement
from app.models.player import Player
from app.services.access import consent_signature, consent_subquery, has_consent


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

from ml.challengers import xgb_forecast  # noqa: E402
from ml.forecasting.models import (  # noqa: E402
    PlayerHistory,
    Snapshot,
    age_at,
    cohort_velocity,
    last_value,
)
from ml.forecasting.walk_forward import (  # noqa: E402
    INTERVAL_COVERAGE,
    INTERVAL_MODEL,
    MIN_INTERVAL_HISTORY,
    MIN_READINGS,
    band_coverage,
    build_cases,
    horizon_band,
    quantile,
)

logger = logging.getLogger(__name__)

_TAIL = (1 - INTERVAL_COVERAGE) / 2

YOUTH_MODEL = xgb_forecast.NAME
ADULT_MODEL = "baseline: last value"
ADULT_AGE = 18

# What the walk-forward run scores. Cohort velocity is not drawn, but build_cases needs it for
# the evaluation's own band, so it rides along; it costs next to nothing.
_FORECASTERS = {
    INTERVAL_MODEL: cohort_velocity,
    ADULT_MODEL: last_value,
    YOUTH_MODEL: xgb_forecast.xgboost_forecast,
}

# The horizons drawn on the profile: the end of each band the evaluation scores.
HORIZONS_DAYS = (91, 182, 365)
# A last reading older than this is further out than the model was ever checked.
MAX_STALENESS_DAYS = 365

_TTL_SECONDS = 300


@dataclass
class _Model:
    built_at: float = 0.0
    # The consent table as it was when this model was built (see access.consent_signature).
    consents: tuple = ()
    snapshot: Snapshot | None = None
    # XGBoost trained on `snapshot`, or None when the database is too small to train it.
    regressor: Any = None
    # (group, gender, horizon band) -> errors (actual minus predicted) of past forecasts, cm.
    errors: dict[tuple[str, str, str], list[float]] = field(default_factory=dict)
    # (group, gender) -> [readings inside the band, forecasts that had a band], walk-forward.
    coverage: dict[tuple[str, str], list[int]] = field(default_factory=dict)


_model = _Model()
# Guards `_model`, `_refreshing` and `_generation`. Never held during a build.
_lock = threading.Lock()
# One build at a time. The walk-forward run goes through xgb_forecast's module-level cache,
# which is not safe to share between threads.
_build_lock = threading.Lock()
# Requests that find no model queue here, so they wait for one build instead of each
# starting their own.
_first_build_lock = threading.Lock()
_refreshing = False
# Bumped by reset_cache, so a build that started before a reset never installs its result.
_generation = 0


def _histories(db: Session, today: date) -> dict[str, PlayerHistory]:
    players = db.execute(
        select(Player.id, Player.sex, Player.date_of_birth)
        .where(Player.status != PlayerStatus.MERGED.value)
        .where(Player.date_of_birth.is_not(None))
        .where(Player.id.in_(consent_subquery(ConsentPurpose.ANALYTICS.value, today)))
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


def _player_history(db: Session, player: Player) -> PlayerHistory:
    rows = db.execute(
        select(Measurement.measured_at, Measurement.value)
        .where(Measurement.player_id == player.id)
        .where(Measurement.metric == "height_cm")
        .where(Measurement.value.is_not(None))
        .order_by(Measurement.measured_at)
    ).all()
    return PlayerHistory(
        str(player.id), player.sex, player.date_of_birth, [(d, float(v)) for d, v in rows]
    )


def _group(stated_age: float) -> str:
    return "youth" if stated_age < ADULT_AGE else "adult"


def _build(db: Session, today: date) -> _Model:
    consents = consent_signature(db, ConsentPurpose.ANALYTICS.value, today)
    histories = _histories(db, today)
    model = _Model(built_at=time.time(), consents=consents)
    model.snapshot = Snapshot(today, histories)

    with _build_lock:
        _, cases = build_cases(histories, _FORECASTERS)
        model.regressor = xgb_forecast.train(model.snapshot)

    def key(case) -> tuple[str, str, str]:
        return (_group(case.stated_age), case.sex, horizon_band(case.horizon_days))

    def predicted(case) -> float | None:
        return case.predictions.get(
            YOUTH_MODEL if _group(case.stated_age) == "youth" else ADULT_MODEL
        )

    # Coverage, checked the way the evaluation checks it: at each origin, the band comes only
    # from forecasts whose outcome had already been measured by then, for the same group,
    # gender and horizon. Calibrating on the future would make the check meaningless.
    for (group, sex, _), (hits, banded, _) in band_coverage(cases, predicted, key).items():
        tally = model.coverage.setdefault((group, sex), [0, 0])
        tally[0] += int(hits)
        tally[1] += int(banded)

    # The band shown today learns from every past forecast whose outcome is known.
    for case in cases:
        value = predicted(case)
        if value is not None:
            model.errors.setdefault(key(case), []).append(case.actual - value)
    return model


def _install(fresh: _Model, generation: int) -> None:
    global _model
    with _lock:
        if generation == _generation:
            _model = fresh


def _refresh_in_background(today: date, generation: int) -> None:
    global _refreshing
    from app.db import SessionLocal

    try:
        with SessionLocal() as db:
            _install(_build(db, today), generation)
    finally:
        with _lock:
            _refreshing = False


def _get_model(db: Session, today: date) -> _Model:
    global _refreshing
    consents = consent_signature(db, ConsentPurpose.ANALYTICS.value, today)
    with _lock:
        current, generation = _model, _generation
        if current.snapshot is not None:
            # Out of date (older than the TTL, or built on an earlier day): keep serving it
            # while one background thread builds the next. Yesterday's model is still a model
            # learned from every reading up to yesterday.
            out_of_date = (
                time.time() - current.built_at > _TTL_SECONDS
                or current.snapshot.origin != today
                or current.consents != consents
            )
            if out_of_date and not _refreshing:
                _refreshing = True
                threading.Thread(
                    target=_refresh_in_background, args=(today, generation), daemon=True
                ).start()
            return current
    # No model at all: this request waits, and so does anyone else who arrives meanwhile.
    with _first_build_lock:
        with _lock:
            if _model.snapshot is not None:
                return _model
        fresh = _build(db, today)
        _install(fresh, generation)
        return fresh


def warm_up() -> None:
    """Build the model in a background thread when the API starts, so the first profile
    anyone opens does not wait for it. Called from app/main.py."""
    from app.db import SessionLocal

    def run() -> None:
        try:
            with SessionLocal() as db:
                _get_model(db, date.today())
        except Exception:  # noqa: BLE001
            # An empty or unmigrated database, say. The first profile request will build
            # the model instead, and report the problem the normal way.
            logger.exception("Forecast warm-up failed; the first profile request will retry.")

    threading.Thread(target=run, daemon=True).start()


def reset_cache() -> None:
    """Drop the cached model. Used by tests, which change the data underneath it."""
    global _model, _generation
    with _lock:
        _model = _Model()
        _generation += 1


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
    if not has_consent(db, player.id, ConsentPurpose.ANALYTICS.value, today):
        return Forecast(
            [],
            None,
            "No forecast: analytics consent is not in effect for this player, so their "
            "measurements are not used for forecasts.",
        )
    if player.date_of_birth is None or player.sex is None:
        return Forecast([], None, "No forecast: the date of birth or sex is not recorded.")

    history = _player_history(db, player)
    if len(history.heights) < MIN_READINGS:
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

    model = _get_model(db, today)
    group = _group(age_at(history.dob, today))

    def centre_at(target: date) -> float | None:
        if group == "youth":
            return xgb_forecast.predict(model.regressor, model.snapshot, history, target)
        return last_value(model.snapshot, history, target)

    points: list[dict] = []
    for days in HORIZONS_DAYS:
        errors = model.errors.get((group, history.sex, horizon_band(days)), [])
        if len(errors) < MIN_INTERVAL_HISTORY:
            # A band from a handful of cases is not a band. Stop rather than draw one.
            break
        target = today + timedelta(days=days)
        centre = centre_at(target)
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
            f"XGBoost: learned from this database's growth records, using the last "
            f"measurement, the player's own recent growth rate and what is typical for their "
            f"age and sex. The shaded area is where {coverage} of readings should "
            f"fall.{checked}"
        )
    else:
        note = (
            f"Adult: growth has finished, so the forecast is flat at the last measurement. The "
            f"shaded area is where {coverage} of readings should fall, which is mostly "
            f"measurement error."
        )
    return Forecast(points, today, note)
