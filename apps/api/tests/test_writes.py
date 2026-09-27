"""Adding a player and logging a measurement.

Three things are tested hard here, because each is a way this screen could hurt a child's
record without anyone noticing:

  Who may write. Only a coach (into their own organization) or an admin adds players, and
  only someone who may log for a player logs for them. Every refusal also checks that nothing
  was saved, since a 403 that still wrote the row is worse than no check at all.

  Minor status is the server's call. A client that says a 12 year old is an adult is ignored.

  Surprising readings are a question, never a block and never silent. 409 and nothing saved
  the first time, saved with an audit record of who confirmed it the second.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from tests.conftest import TODAY


def _years_ago(years: int, extra_days: int = 0) -> str:
    return (date(TODAY.year - years, TODAY.month, min(TODAY.day, 28)) - timedelta(days=extra_days)).isoformat()


def new_player(**overrides) -> dict:
    body = {
        "fullName": "Karim Test Player",
        "dateOfBirth": _years_ago(13),
        "sex": "male",
        "nationality": ["EG"],
        "isEgyptEligible": True,
        "primarySport": "football",
        "tier": "youth",
        "position": "ST",
        "measurements": {
            "measuredAt": TODAY.isoformat(),
            "metrics": [
                {"metric": "height_cm", "value": 152.5, "unit": "cm"},
                {"metric": "weight_kg", "value": 41, "unit": "kg"},
            ],
        },
    }
    body.update(overrides)
    return body


def players_named(db, name: str) -> int:
    from app.models.player import Player

    return db.execute(select(func.count()).where(Player.full_name == name)).scalar_one()


def audit_rows(db, action: str, entity_id) -> list:
    from app.models.audit_log import AuditLog

    return list(
        db.execute(
            select(AuditLog)
            .where(AuditLog.action == action)
            .where(AuditLog.entity_id == entity_id)
        ).scalars()
    )


# ---------------------------------------------------------------------------
# Who may add a player
# ---------------------------------------------------------------------------


def test_coach_adds_a_player_who_then_appears_in_their_squad(client, auth, world, db):
    """The whole point: the demo's first step, end to end through the API."""
    response = client.post("/players", json=new_player(), headers=auth("coach_a"))
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["organizationId"] == str(world["orgs"]["a"].id)
    assert {m["metric"] for m in body["measurements"]} == {"height_cm", "weight_kg"}

    squad = client.get("/players", headers=auth("coach_a")).json()
    row = next(r for r in squad if r["player"]["id"] == body["player"]["id"])
    assert row["heightCm"] == 152.5

    profile = client.get(f"/players/{body['player']['id']}/profile", headers=auth("coach_a"))
    assert profile.status_code == 200


def test_new_player_is_not_in_another_academys_squad(client, auth, world):
    created = client.post("/players", json=new_player(), headers=auth("coach_a")).json()
    squad_b = client.get("/players", headers=auth("coach_b")).json()
    assert created["player"]["id"] not in {r["player"]["id"] for r in squad_b}


def test_coach_cannot_add_a_player_to_another_organization(client, auth, world, db):
    """Refused, not silently redirected to their own academy."""
    body = new_player(organizationId=str(world["orgs"]["b"].id))
    response = client.post("/players", json=body, headers=auth("coach_a"))
    assert response.status_code == 403
    assert players_named(db, body["fullName"]) == 0


def test_coach_may_name_their_own_organization(client, auth, world):
    body = new_player(organizationId=str(world["orgs"]["a"].id))
    assert client.post("/players", json=body, headers=auth("coach_a")).status_code == 201


@pytest.mark.parametrize("who", ["scout", "federation", "player_self", "coach_orphan"])
def test_roles_that_may_not_add_players_are_refused(client, auth, world, db, who):
    body = new_player(fullName=f"Refused {who}")
    response = client.post("/players", json=body, headers=auth(who))
    assert response.status_code == 403
    assert players_named(db, body["fullName"]) == 0


def test_no_identity_cannot_add_a_player(client, world):
    assert client.post("/players", json=new_player()).status_code == 401


def test_admin_must_name_an_organization(client, auth, world):
    assert client.post("/players", json=new_player(), headers=auth("admin")).status_code == 403

    body = new_player(organizationId=str(world["orgs"]["b"].id))
    response = client.post("/players", json=body, headers=auth("admin"))
    assert response.status_code == 201
    assert response.json()["organizationId"] == str(world["orgs"]["b"].id)


def test_admin_naming_a_missing_organization_is_refused(client, auth, world, db):
    body = new_player(organizationId=str(uuid.uuid4()))
    response = client.post("/players", json=body, headers=auth("admin"))
    assert response.status_code == 422
    assert players_named(db, body["fullName"]) == 0


# ---------------------------------------------------------------------------
# Minors and consent
# ---------------------------------------------------------------------------


def test_minor_status_comes_from_the_date_of_birth_not_the_client(client, auth, world):
    body = new_player(isMinor=False, dateOfBirth=_years_ago(12))
    created = client.post("/players", json=body, headers=auth("coach_a")).json()
    assert created["player"]["isMinor"] is True
    assert created["consentRequired"] is True


def test_adult_is_not_a_minor(client, auth, world):
    body = new_player(dateOfBirth=_years_ago(22), tier="pro")
    created = client.post("/players", json=body, headers=auth("coach_a")).json()
    assert created["player"]["isMinor"] is False
    assert created["consentRequired"] is False


@pytest.mark.parametrize(
    ("dob", "on", "minor"),
    [
        (date(2008, 6, 15), date(2026, 6, 14), True),  # the day before their 18th birthday
        (date(2008, 6, 15), date(2026, 6, 15), False),  # their 18th birthday
        (date(2008, 2, 29), date(2026, 2, 28), True),  # leap day births turn 18 on 1 March
        (date(2008, 2, 29), date(2026, 3, 1), False),
    ],
)
def test_minor_boundary_is_the_birthday(dob, on, minor):
    from app.services.writes import is_minor_on

    assert is_minor_on(dob, on) is minor


def test_new_minor_is_withheld_from_scouts(client, auth, world):
    """No consent is written on creation, and absence of consent is not consent."""
    created = client.post("/players", json=new_player(), headers=auth("coach_a")).json()
    player_id = created["player"]["id"]
    assert client.get(f"/players/{player_id}/profile", headers=auth("scout")).status_code == 404


def test_creation_is_audited(client, auth, world, db):
    created = client.post("/players", json=new_player(), headers=auth("coach_a")).json()
    player_id = uuid.UUID(created["player"]["id"])

    (row,) = audit_rows(db, "player.create", player_id)
    assert row.actor_user_id == world["users"]["coach_a"].id
    assert row.event_metadata["is_minor"] is True
    assert row.event_metadata["consent_recorded"] is False
    assert len(audit_rows(db, "measurement.create", player_id)) == 1


# ---------------------------------------------------------------------------
# Refused outright
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"dateOfBirth": (TODAY + timedelta(days=3)).isoformat()}, "future"),
        ({"dateOfBirth": _years_ago(3)}, "under"),
        ({"primarySport": "table_tennis", "tier": "youth"}, "football players only"),
        (
            {
                "measurements": {
                    "measuredAt": _years_ago(20),
                    "metrics": [{"metric": "height_cm", "value": 150, "unit": "cm"}],
                }
            },
            "before the player was born",
        ),
        (
            {
                "measurements": {
                    "measuredAt": TODAY.isoformat(),
                    "metrics": [{"metric": "wingspan_cm", "value": 150, "unit": "cm"}],
                }
            },
            "Unknown metric",
        ),
        (
            {
                "measurements": {
                    "measuredAt": TODAY.isoformat(),
                    "metrics": [{"metric": "weight_kg", "value": 41, "unit": "lb"}],
                }
            },
            "recorded in kg",
        ),
    ],
)
def test_impossible_input_is_refused_and_nothing_is_saved(
    client, auth, world, db, overrides, fragment
):
    body = new_player(**overrides)
    response = client.post("/players", json=body, headers=auth("coach_a"))
    assert response.status_code == 422, response.text
    assert fragment in " ".join(response.json()["detail"]["problems"])
    assert players_named(db, body["fullName"]) == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"nationality": ["EGY"]},
        {"sex": "boy"},
        {"primarySport": "cricket"},
        {"fullName": " "},
    ],
)
def test_malformed_fields_are_refused(client, auth, world, overrides):
    response = client.post("/players", json=new_player(**overrides), headers=auth("coach_a"))
    assert response.status_code == 422


def test_nationality_is_normalised(client, auth, world):
    body = new_player(nationality=["eg", "IT", "EG"])
    created = client.post("/players", json=body, headers=auth("coach_a")).json()
    assert created["player"]["nationality"] == ["EG", "IT"]


# ---------------------------------------------------------------------------
# A question, never a block
# ---------------------------------------------------------------------------


def _implausible_new_player() -> dict:
    return new_player(
        fullName="Implausible Height",
        measurements={
            "measuredAt": TODAY.isoformat(),
            "metrics": [{"metric": "height_cm", "value": 15.2, "unit": "cm"}],
        },
    )


def test_implausible_reading_is_asked_about_and_not_saved(client, auth, world, db):
    body = _implausible_new_player()
    response = client.post("/players", json=body, headers=auth("coach_a"))
    assert response.status_code == 409
    (warning,) = response.json()["detail"]["warnings"]
    assert warning["metric"] == "height_cm"
    assert players_named(db, body["fullName"]) == 0


def test_confirmed_implausible_reading_is_saved_and_the_confirmation_audited(
    client, auth, world, db
):
    body = _implausible_new_player()
    body["measurements"]["acknowledgeWarnings"] = True
    response = client.post("/players", json=body, headers=auth("coach_a"))
    assert response.status_code == 201, response.text
    created = response.json()
    assert len(created["acknowledgedWarnings"]) == 1

    (row,) = audit_rows(db, "measurement.create", uuid.UUID(created["player"]["id"]))
    assert row.actor_user_id == world["users"]["coach_a"].id
    assert row.event_metadata["acknowledged_warnings"][0]["metric"] == "height_cm"


def _visit(value: float, *, days_ago: int = 0, acknowledge: bool = False) -> dict:
    return {
        "measuredAt": (TODAY - timedelta(days=days_ago)).isoformat(),
        "metrics": [{"metric": "height_cm", "value": value, "unit": "cm"}],
        "acknowledgeWarnings": acknowledge,
    }


def test_ordinary_growth_saves_without_a_question(client, auth, world):
    """The fixture's last reading is 160 cm thirty days ago."""
    player_id = world["players"]["adult_a"].id
    response = client.post(
        f"/players/{player_id}/measurements", json=_visit(161.5), headers=auth("coach_a")
    )
    assert response.status_code == 201, response.text
    assert response.json()["acknowledgedWarnings"] == []


@pytest.mark.parametrize(("value", "fragment"), [(155.0, "shorter"), (170.0, "taller")])
def test_surprising_change_against_history_is_asked_about(
    client, auth, world, value, fragment
):
    player_id = world["players"]["adult_a"].id
    response = client.post(
        f"/players/{player_id}/measurements", json=_visit(value), headers=auth("coach_a")
    )
    assert response.status_code == 409
    assert fragment in response.json()["detail"]["warnings"][0]["message"]

    confirmed = client.post(
        f"/players/{player_id}/measurements",
        json=_visit(value, acknowledge=True),
        headers=auth("coach_a"),
    )
    assert confirmed.status_code == 201


def test_logged_measurement_records_who_and_how(client, auth, world, db):
    from app.models.measurement import Measurement

    player_id = world["players"]["adult_a"].id
    saved = client.post(
        f"/players/{player_id}/measurements", json=_visit(160.5), headers=auth("coach_a")
    ).json()
    row = db.get(Measurement, uuid.UUID(saved["measurements"][0]["id"]))
    assert row.source == "coach_logged"
    assert row.recorded_by == world["users"]["coach_a"].id
    assert row.confidence == "measured"


def test_future_measurement_is_refused(client, auth, world):
    player_id = world["players"]["adult_a"].id
    response = client.post(
        f"/players/{player_id}/measurements", json=_visit(160.5, days_ago=-2), headers=auth("coach_a")
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Who may log a measurement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "target", "expected"),
    [
        ("coach_a", "adult_a", 201),
        ("admin", "adult_b", 201),
        # Outside their scope: indistinguishable from a player who does not exist.
        ("coach_b", "adult_a", 404),
        ("scout", "minor_no_a", 404),
        # They can see the player, so there is nothing to hide; they just may not log.
        ("scout", "adult_a", 403),
        ("federation", "adult_a", 403),
        ("player_self", "adult_a", 403),
    ],
)
def test_who_may_log_a_measurement(client, auth, world, db, who, target, expected):
    from app.models.measurement import Measurement

    player_id = world["players"][target].id
    before = db.execute(
        select(func.count()).where(Measurement.player_id == player_id)
    ).scalar_one()

    response = client.post(
        f"/players/{player_id}/measurements", json=_visit(160.5), headers=auth(who)
    )
    assert response.status_code == expected, response.text

    after = db.execute(
        select(func.count()).where(Measurement.player_id == player_id)
    ).scalar_one()
    assert after == before + (1 if expected == 201 else 0)


def test_logging_for_an_unknown_player_is_404(client, auth, world):
    response = client.post(
        f"/players/{uuid.uuid4()}/measurements", json=_visit(160.5), headers=auth("coach_a")
    )
    assert response.status_code == 404
