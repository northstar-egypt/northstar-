"""The squad's height-readings nudge (app/services/views.py height_readings_needed).

The late-bloomer check cannot fire on a player with fewer than three height readings, and the
backtest found it flagged none of the late bloomers it had measured fewer times. The nudge
tells the coach which players those are. The rule must be the detector's own, so these tests
read the detector's parameters rather than restating the numbers.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.services.views import LATE_BLOOMER, height_readings_needed

TODAY = date(2026, 10, 16)
FEW = LATE_BLOOMER.min_measurements - 1
ENOUGH = LATE_BLOOMER.min_measurements


def born(age: float) -> date:
    return TODAY - timedelta(days=round(age * 365.25))


def test_the_rule_is_the_detectors():
    middle = (LATE_BLOOMER.min_age + LATE_BLOOMER.max_age) / 2
    assert height_readings_needed(born(middle), FEW, True, TODAY) == 1
    assert height_readings_needed(born(middle), 0, True, TODAY) == ENOUGH
    assert height_readings_needed(born(middle), ENOUGH, True, TODAY) == 0
    assert height_readings_needed(born(middle), ENOUGH + 4, True, TODAY) == 0
    # Outside the ages the check looks at, more readings would not make it run.
    assert height_readings_needed(born(LATE_BLOOMER.min_age - 0.2), 0, True, TODAY) == 0
    assert height_readings_needed(born(LATE_BLOOMER.max_age + 0.2), 0, True, TODAY) == 0
    assert height_readings_needed(born(LATE_BLOOMER.min_age + 0.01), 0, True, TODAY) == ENOUGH


def test_no_nudge_without_analytics_consent_or_a_date_of_birth():
    middle = (LATE_BLOOMER.min_age + LATE_BLOOMER.max_age) / 2
    assert height_readings_needed(born(middle), FEW, False, TODAY) == 0
    assert height_readings_needed(None, FEW, True, TODAY) == 0


def _row(client, auth, player):
    rows = client.get("/players", headers=auth("coach_a")).json()
    return next(r for r in rows if r["player"]["id"] == str(player.id))


def test_the_squad_marks_a_player_with_too_few_readings(client, auth, world, db):
    from app.models.measurement import Measurement

    player = world["players"]["minor_ok_a"]  # 15, six readings in the test world
    row = _row(client, auth, player)
    assert row["heightReadings"] == 6
    assert row["heightReadingsNeeded"] == 0

    readings = (
        db.query(Measurement)
        .filter_by(player_id=player.id, metric="height_cm")
        .order_by(Measurement.measured_at)
        .all()
    )
    for extra in readings[FEW:]:
        db.delete(extra)
    db.flush()

    row = _row(client, auth, player)
    assert row["heightReadings"] == FEW
    assert row["heightReadingsNeeded"] == ENOUGH - FEW


def test_no_nudge_once_analytics_consent_is_withdrawn(client, auth, world, db):
    from app.models.measurement import Measurement
    from tests.conftest import withdraw_analytics

    player = world["players"]["minor_ok_a"]
    db.query(Measurement).filter_by(player_id=player.id, metric="height_cm").delete()
    withdraw_analytics(db, player)
    db.flush()
    row = _row(client, auth, player)
    assert row["heightReadings"] == 0
    assert row["heightReadingsNeeded"] == 0


def test_an_adult_is_never_nudged(client, auth, world, db):
    from app.models.measurement import Measurement

    player = world["players"]["adult_a"]  # 24
    db.query(Measurement).filter_by(player_id=player.id, metric="height_cm").delete()
    db.flush()
    assert _row(client, auth, player)["heightReadingsNeeded"] == 0
