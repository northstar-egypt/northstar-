"""The height forecast on the player profile.

The test that matters most is the first one: the number on the screen must be the graded model
in ml/forecasting run on this database, not a re-implementation that drifts from it. After that,
the band is always there around a forecast, adults get a flat line, and every "no forecast" case
says why instead of drawing something.

The population is built here, inside the rolled-back transaction, so the tests do not depend on
whatever the database was seeded with. If the database also holds the synthetic dataset, the
model learns from both, which is why assertions compare against the model rather than against
fixed centimetres.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tests.conftest import TODAY


@pytest.fixture
def population(db, world):
    """Sixty children and twenty adults, measured every 60 days for three years.

    Children grow 6 cm a year with a little deterministic wobble, so the walk-forward run has
    hundreds of past forecasts per horizon to learn a band from.
    """
    from app.models.measurement import Measurement
    from app.models.player import Player

    def add(name: str, dob: date, start_cm: float, rate: float) -> Player:
        player = Player(
            id=uuid.uuid4(),
            full_name=name,
            date_of_birth=dob,
            sex="male",
            nationality=["EG"],
            primary_sport="football",
            is_minor=(TODAY - dob).days < 18 * 365.25,
        )
        db.add(player)
        when = TODAY - timedelta(days=3 * 365)
        index = 0
        while when <= TODAY - timedelta(days=20):
            years = (when - (TODAY - timedelta(days=3 * 365))).days / 365.25
            wobble = ((index * 7) % 5 - 2) * 0.2
            db.add(
                Measurement(
                    player_id=player.id,
                    measured_at=when,
                    metric="height_cm",
                    value=Decimal(str(round(start_cm + rate * years + wobble, 1))),
                    unit="cm",
                    source="coach_logged",
                )
            )
            when += timedelta(days=60)
            index += 1
        return player

    kids = [
        add(f"Forecast Child {i}", TODAY - timedelta(days=int((10 + i % 6) * 365.25)), 135 + i % 9, 6.0)
        for i in range(60)
    ]
    adults = [
        add(f"Forecast Adult {i}", TODAY - timedelta(days=int((22 + i % 8) * 365.25)), 170 + i % 7, 0.0)
        for i in range(20)
    ]
    db.flush()
    from app.services import forecast

    forecast.reset_cache()
    return {"kids": kids, "adults": adults}


def test_the_profile_forecast_is_the_graded_model(db, population):
    """Same number as ml/forecasting's cohort velocity on the same rows, to the millimetre."""
    # The service first: importing it is what puts the repository's ml/ on the path.
    from app.services import forecast
    from ml.forecasting.models import Snapshot, cohort_velocity

    child = population["kids"][0]
    result = forecast.forecast_height(db, child, today=TODAY)
    assert len(result.points) == 3

    histories = forecast._histories(db)
    snapshot = Snapshot(TODAY, histories)
    for point in result.points:
        expected = cohort_velocity(snapshot, histories[str(child.id)], point["date"])
        assert point["value"] == pytest.approx(round(expected, 1))


def test_every_point_carries_a_band_around_it(db, population):
    from app.services import forecast

    result = forecast.forecast_height(db, population["kids"][3], today=TODAY)
    assert [p["date"] for p in result.points] == [
        TODAY + timedelta(days=d) for d in forecast.HORIZONS_DAYS
    ]
    for point in result.points:
        assert point["lower"] < point["value"] < point["upper"]
    assert result.origin == TODAY
    assert "80%" in result.note and "fell inside the band" in result.note


def test_a_growing_child_is_forecast_to_grow(db, population):
    from app.services import forecast

    child = population["kids"][5]
    last = float(max(child.measurements, key=lambda m: m.measured_at).value)
    result = forecast.forecast_height(db, child, today=TODAY)
    assert result.points[-1]["value"] > last


def test_an_adult_gets_a_flat_line(db, population):
    """The evaluation showed the model keeps adults growing, so they get last value."""
    from app.services import forecast

    adult = population["adults"][0]
    last = float(max(adult.measurements, key=lambda m: m.measured_at).value)
    result = forecast.forecast_height(db, adult, today=TODAY)
    assert result.points
    assert {p["value"] for p in result.points} == {round(last, 1)}
    assert result.note.startswith("Adult")


def test_one_reading_is_not_enough(db, population):
    from app.models.measurement import Measurement
    from app.models.player import Player
    from app.services import forecast

    player = Player(
        id=uuid.uuid4(),
        full_name="One Reading",
        date_of_birth=TODAY - timedelta(days=12 * 365),
        sex="male",
        nationality=["EG"],
        primary_sport="football",
        is_minor=True,
    )
    db.add(player)
    db.add(
        Measurement(
            player_id=player.id,
            measured_at=TODAY - timedelta(days=10),
            metric="height_cm",
            value=Decimal("150.0"),
            unit="cm",
            source="coach_logged",
        )
    )
    db.flush()
    forecast.reset_cache()
    result = forecast.forecast_height(db, player, today=TODAY)
    assert result.points == []
    assert "at least two" in result.note


def test_a_stale_history_gets_no_forecast(db, population):
    """A year after the last reading is beyond anything the model was checked on."""
    from app.services import forecast

    child = population["kids"][1]
    later = TODAY + timedelta(days=400)
    result = forecast.forecast_height(db, child, today=later)
    assert result.points == []
    assert "more than a year ago" in result.note


def test_no_band_means_no_forecast(db, population, monkeypatch):
    """With too little history to learn a band from, nothing is drawn at all."""
    from app.services import forecast

    monkeypatch.setattr(forecast, "MIN_INTERVAL_HISTORY", 10**9)
    result = forecast.forecast_height(db, population["kids"][2], today=TODAY)
    assert result.points == []
    assert "uncertainty band" in result.note


def test_missing_date_of_birth_is_said_plainly(db, population):
    from app.services import forecast

    child = population["kids"][4]
    child.date_of_birth = None
    result = forecast.forecast_height(db, child, today=TODAY)
    assert result.points == []
    assert "date of birth" in result.note


def test_the_profile_endpoint_carries_the_forecast(client, auth, db, population):
    """End to end through the API, as the admin (who may view any player)."""
    child = population["kids"][0]
    growth = client.get(f"/players/{child.id}/profile", headers=auth("admin")).json()["growth"]
    assert len(growth["forecast"]) == 3
    assert growth["forecastFrom"] == TODAY.isoformat()
    assert growth["forecastNote"].startswith("Cohort velocity")
    for point in growth["forecast"]:
        assert point["lower"] < point["value"] < point["upper"]
