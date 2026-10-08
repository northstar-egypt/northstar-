"""Recording a withdrawal of consent: POST /players/{id}/consent/withdraw.

A guardian signs one form at sign-up and may withdraw part of it at any time. The coach (or an
admin, or an adult player for themselves) records the withdrawal; it takes effect at once
everywhere consent is checked, and nothing about the earlier grant is deleted.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.conftest import TODAY


def _withdraw(client, auth, who: str, player, purposes, guardian: str | None = "Test Guardian"):
    body = {"purposes": purposes}
    if guardian is not None:
        body["guardianName"] = guardian
    return client.post(
        f"/players/{player.id}/consent/withdraw", json=body, headers=auth(who)
    )


def test_a_coach_records_a_guardians_withdrawal_of_analytics(client, auth, db, world):
    player = world["players"]["minor_ok_a"]
    response = _withdraw(client, auth, "coach_a", player, ["analytics"], "Mona Hassan")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["withdrawn"] == ["analytics"]
    assert body["alreadyWithdrawn"] == []
    assert body["withdrawnBy"] == "guardian:Mona Hassan"
    assert body["consents"] == {
        "data_storage": True,
        "analytics": False,
        "scouting_visibility": True,
    }

    # It reaches the analytics at once: the profile withholds percentiles and the forecast.
    profile = client.get(f"/players/{player.id}/profile", headers=auth("coach_a")).json()
    assert "analytics consent" in profile["percentilesNote"]
    assert "analytics consent" in profile["growth"]["forecastNote"]


def test_nothing_about_the_grant_is_deleted(client, auth, db, world):
    """The grant is closed the day before, and a "not granted" row starts today, so the record
    says when consent ended and on whose word."""
    from app.models.consent import Consent

    player = world["players"]["minor_ok_a"]
    _withdraw(client, auth, "coach_a", player, ["analytics"], "Mona Hassan")
    rows = (
        db.query(Consent)
        .filter_by(player_id=player.id, purpose="analytics")
        .order_by(Consent.valid_from)
        .all()
    )
    assert [(r.granted, r.valid_until) for r in rows] == [
        (True, TODAY - timedelta(days=1)),
        (False, None),
    ]
    assert rows[1].valid_from == TODAY
    assert rows[1].granted_by == "guardian:Mona Hassan"


def test_the_withdrawal_is_audited(client, auth, db, world):
    from app.models.audit_log import AuditLog

    player = world["players"]["minor_ok_a"]
    _withdraw(client, auth, "coach_a", player, ["analytics", "scouting_visibility"])
    row = (
        db.query(AuditLog)
        .filter_by(entity_id=player.id, action="consent.withdraw")
        .one()
    )
    assert row.actor_user_id == world["users"]["coach_a"].id
    assert row.event_metadata["purposes"] == ["analytics", "scouting_visibility"]
    assert row.event_metadata["withdrawn_by"] == "guardian:Test Guardian"


def test_withdrawing_scouting_visibility_hides_a_minor_from_scouts(client, auth, world):
    player = world["players"]["minor_ok_a"]
    url = f"/players/{player.id}/profile"
    assert client.get(url, headers=auth("scout")).status_code == 200
    assert _withdraw(client, auth, "coach_a", player, ["scouting_visibility"]).status_code == 200
    assert client.get(url, headers=auth("scout")).status_code != 200
    # The coach who holds the form still sees the child.
    assert client.get(url, headers=auth("coach_a")).status_code == 200


def test_repeating_a_withdrawal_is_harmless(client, auth, world):
    player = world["players"]["minor_ok_a"]
    _withdraw(client, auth, "coach_a", player, ["analytics"])
    again = _withdraw(client, auth, "coach_a", player, ["analytics"]).json()
    assert again["withdrawn"] == []
    assert again["alreadyWithdrawn"] == ["analytics"]


def test_an_adult_player_withdraws_for_themselves(client, auth, world):
    player = world["players"]["adult_a"]
    response = _withdraw(client, auth, "player_self", player, ["analytics"], guardian=None)
    assert response.status_code == 200, response.text
    assert response.json()["withdrawnBy"] == "player"


def test_a_minors_withdrawal_names_the_guardian(client, auth, db, world):
    from app.services.access import consent_state

    player = world["players"]["minor_ok_a"]
    response = _withdraw(client, auth, "coach_a", player, ["analytics"], guardian="  ")
    assert response.status_code == 422
    assert "guardian" in " ".join(response.json()["detail"]["problems"])
    assert consent_state(db, player.id)["analytics"] is True


def test_data_storage_is_an_erasure_not_a_withdrawal(client, auth, db, world):
    from app.services.access import consent_state

    player = world["players"]["minor_ok_a"]
    response = _withdraw(client, auth, "coach_a", player, ["analytics", "data_storage"])
    assert response.status_code == 422
    assert "erasure" in " ".join(response.json()["detail"]["problems"])
    # All or nothing: the analytics part was not saved either.
    assert consent_state(db, player.id)["analytics"] is True


def test_an_unknown_purpose_is_refused(client, auth, world):
    response = _withdraw(client, auth, "coach_a", world["players"]["minor_ok_a"], ["marketing"])
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("who", "expected"),
    [
        ("scout", 403),  # may see the player, does not hold the form
        ("federation", 403),
        ("coach_b", 404),  # another academy's player does not exist for them
    ],
)
def test_only_someone_who_may_edit_the_record_may_record_it(
    client, auth, db, world, who, expected
):
    from app.services.access import consent_state

    player = world["players"]["minor_ok_a"]
    assert _withdraw(client, auth, who, player, ["analytics"]).status_code == expected
    assert consent_state(db, player.id)["analytics"] is True


def test_signing_in_is_required(client, world):
    player = world["players"]["minor_ok_a"]
    response = client.post(
        f"/players/{player.id}/consent/withdraw", json={"purposes": ["analytics"]}
    )
    assert response.status_code == 401
