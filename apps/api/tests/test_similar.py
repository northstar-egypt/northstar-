"""GET /players/{id}/similar (app/services/similar.py).

What matters here is who appears: only players the caller may see, and only players whose
analytics consent is in effect. How good the similarity is, is measured by
`python -m ml.run_similarity_eval`.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

SHOTS = {"adult_a": 3, "minor_ok_a": 3, "minor_no_a": 2, "adult_b": 3, "minor_no_b": 3}


def _matches(db, player, shots: int, n: int = 6):
    from app.models.enums import PerformanceSource
    from app.models.performance_entry import PerformanceEntry

    for i in range(n):
        db.add(
            PerformanceEntry(
                id=uuid.uuid4(),
                player_id=player.id,
                sport="football",
                period_type="match",
                period_start=date(2026, 1, 1) + timedelta(days=7 * i),
                metrics={
                    "minutes_played": 90, "shots": shots, "shots_on_target": 1, "goals": 0,
                    "assists": 0, "key_passes": 1, "tackles": 2, "passes_attempted": 40,
                    "passes_completed": 32, "distance_km": 10.0, "yellow_cards": 0,
                    "red_cards": 0,
                },
                schema_ref="football.match.v1",
                source=PerformanceSource.COACH_LOGGED.value,
                is_validated=True,
            )
        )


@pytest.fixture
def records(db, world):
    for name, shots in SHOTS.items():
        _matches(db, world["players"][name], shots)
    db.flush()
    return world


def _similar(client, auth, who, player):
    return client.get(f"/players/{player.id}/similar", headers=auth(who))


def _names(response):
    return {item["fullName"] for item in response.json()["items"]}


def test_a_coach_sees_only_their_own_squad_among_similar_players(client, auth, records):
    response = _similar(client, auth, "coach_a", records["players"]["adult_a"])
    assert response.status_code == 200
    names = _names(response)
    assert names, "the squad has comparable players, so the list should not be empty"
    assert names <= {"Minor Consented A", "Minor Blocked A"}
    first = response.json()["items"][0]
    assert first["fullName"] == "Minor Consented A"  # an identical record
    assert first["alike"]


def test_a_scout_never_sees_a_withheld_minor_in_the_list(client, auth, records):
    names = _names(_similar(client, auth, "scout", records["players"]["adult_a"]))
    assert "Minor Blocked A" not in names and "Minor Blocked B" not in names
    assert "Adult B" in names


def test_without_analytics_consent_a_player_is_neither_compared_nor_listed(
    client, auth, records, db
):
    from tests.conftest import withdraw_analytics

    withdrawn = records["players"]["minor_ok_a"]
    withdraw_analytics(db, withdrawn)
    names = _names(_similar(client, auth, "federation", records["players"]["adult_a"]))
    assert "Minor Consented A" not in names

    own = _similar(client, auth, "federation", withdrawn).json()
    assert own["items"] == []
    assert "consent" in own["note"].lower()


def test_too_little_time_on_record_is_said_not_guessed(client, auth, world):
    body = _similar(client, auth, "federation", world["players"]["adult_a"]).json()
    assert body["items"] == []
    assert "450 minutes" in body["note"]


def test_a_player_the_caller_may_not_see_is_404(client, auth, records):
    response = _similar(client, auth, "scout", records["players"]["minor_no_a"])
    assert response.status_code == 404
