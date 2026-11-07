"""The growth rate on the coach's home (app/services/views.py growth_cm_per_year).

A number is given only when it can mean something: a child, two readings at least six months
apart, the earlier one recent. Otherwise none, rather than half a centimetre of measuring error
dressed up as a rate.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.services.views import growth_cm_per_year

TODAY = date(2026, 10, 28)
CHILD = date(2013, 1, 1)


def _ago(days: int) -> date:
    return TODAY - timedelta(days=days)


def test_a_childs_growth_over_a_year():
    series = [(_ago(365), 150.0), (_ago(10), 156.0)]
    assert growth_cm_per_year(series, CHILD, TODAY) == pytest.approx(6.2, abs=0.05)


def test_the_earliest_reading_in_the_window_is_used():
    series = [(_ago(700), 140.0), (_ago(380), 148.0), (_ago(200), 151.0), (_ago(5), 154.0)]
    # 700 days ago is outside the 400-day window; 380 days ago is the first inside it.
    assert growth_cm_per_year(series, CHILD, TODAY) == pytest.approx(6.0 * 365.25 / 375, abs=0.05)


@pytest.mark.parametrize(
    "series",
    [
        [],
        [(_ago(5), 154.0)],
        [(_ago(100), 152.0), (_ago(5), 154.0)],  # readings too close together
        [(_ago(600), 140.0), (_ago(5), 154.0)],  # the earlier one too old to say how they grow now
    ],
)
def test_no_rate_without_two_readings_far_enough_apart_and_recent(series):
    assert growth_cm_per_year(series, CHILD, TODAY) is None


def test_no_rate_for_an_adult_or_without_a_birth_date():
    series = [(_ago(365), 180.0), (_ago(10), 180.4)]
    assert growth_cm_per_year(series, date(2000, 1, 1), TODAY) is None
    assert growth_cm_per_year(series, None, TODAY) is None


def test_the_reading_entered_last_on_a_day_counts_as_the_latest(db, world):
    """A coach correcting a typo logs again the same day: the correction is the latest."""
    from datetime import datetime, timezone

    from app.models.measurement import Measurement
    from app.services.views import latest_value, measurement_series

    player = world["players"]["adult_a"]
    day = date(2026, 10, 1)
    for hour, value in ((12, 190.0), (9, 170.0)):  # added out of order, so insertion order proves nothing
        db.add(Measurement(
            player_id=player.id, measured_at=day, metric="height_cm", value=value, unit="cm", source="coach_logged",
            confidence="measured", created_at=datetime(2026, 10, 1, hour, tzinfo=timezone.utc),
        ))
    db.flush()
    series = [p for p in measurement_series(db, [player.id], "height_cm")[player.id] if p[0] == day]
    assert [v for _, v in series] == [170.0, 190.0]
    assert latest_value(series) == 190.0
