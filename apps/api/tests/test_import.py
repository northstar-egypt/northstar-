"""Bulk import of players (app/services/imports.py, POST /players/import/preview and /import).

Every CSV here is built in the test from made-up names. No CSV file is read or written: the
import is the most likely route for real children's data into the project, and test data must
never be a file someone could swap a real export into.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

HEADER = "full_name,date_of_birth,gender,sport,position,nationality,consent_signed,guardian_name,measured_on,height_cm,weight_kg"
TODAY = date.today()


def _dob(age: float) -> str:
    return (TODAY - timedelta(days=round(age * 365.25))).isoformat()


def _row(name="Karim Test Nabil", age=14, sport="football", position="CM", gender="male",
         consent="yes", guardian="Test Guardian", height="158", weight="47", measured=None):
    measured = TODAY.isoformat() if measured is None else measured
    return f"{name},{_dob(age)},{gender},{sport},{position},EG,{consent},{guardian},{measured},{height},{weight}"


def _csv(*rows: str, header: str = HEADER) -> str:
    return "\n".join([header, *rows]) + "\n"


def _preview(client, auth, text, who="coach_a"):
    return client.post("/players/import/preview", json={"csv": text}, headers=auth(who))


def _by_line(body):
    return {row["line"]: row for row in body["rows"]}


def test_a_preview_gives_every_row_a_verdict_and_saves_nothing(client, auth, world, db):
    from app.models.player import Player

    before = db.query(Player).count()
    text = _csv(
        _row(),  # line 2: ready
        _row(name="Omar Test Fathy", guardian=""),  # 3: a minor without a named guardian
        _row(name="Ziad Test Salem", height="260"),  # 4: implausible height, needs confirming
        _row(name="Adam Test Hany", consent="no"),  # 5: consent not signed
        _row(name="Nour Test Adel", sport="football", gender="female"),  # 6: football is boys only
        _row(name="=HYPERLINK(1)"),  # 7: a formula
        _row(name="Ali Test Samir", position="XX"),  # 8: not a football position
    )
    response = _preview(client, auth, text)
    assert response.status_code == 200
    rows = _by_line(response.json())
    assert rows[2]["status"] == "ready"
    assert rows[3]["status"] == "rejected" and "guardian" in " ".join(rows[3]["problems"])
    assert rows[4]["status"] == "confirm" and "outside the usual range" in rows[4]["warnings"][0]
    assert rows[5]["status"] == "rejected" and "consent" in " ".join(rows[5]["problems"]).lower()
    assert rows[6]["status"] == "rejected"
    assert rows[7]["status"] == "rejected" and "formula" in " ".join(rows[7]["problems"])
    assert rows[8]["status"] == "rejected" and "XX" in " ".join(rows[8]["problems"])
    assert response.json()["counts"] == {"ready": 1, "confirm": 1, "rejected": 5}
    assert db.query(Player).count() == before


def test_a_player_already_on_the_platform_needs_confirming(client, auth, world):
    existing = world["players"]["adult_a"]  # "Adult A"
    row = f"Adult A,{existing.date_of_birth.isoformat()},male,football,ST,EG,yes,,,,"
    rows = _by_line(_preview(client, auth, _csv(row)).json())
    assert rows[2]["status"] == "confirm"
    assert "already be on the platform" in rows[2]["warnings"][0]


def test_import_saves_ready_and_confirmed_rows_in_one_go(client, auth, world, db):
    from app.models.audit_log import AuditLog
    from app.models.consent import Consent
    from app.models.player_organization import PlayerOrganization

    text = _csv(
        _row(name="Karim Test Nabil"),  # 2 ready
        _row(name="Ziad Test Salem", height="260"),  # 3 confirm, confirmed below
        _row(name="Hany Test Saad", height="95"),  # 4 confirm, not confirmed
        _row(name="Omar Test Fathy", guardian=""),  # 5 rejected
    )
    response = client.post(
        "/players/import", json={"csv": text, "confirm": [3]}, headers=auth("coach_a")
    )
    assert response.status_code == 200
    body = response.json()
    rows = _by_line(body)
    assert body["saved"] is True
    assert [rows[i]["status"] for i in (2, 3, 4, 5)] == ["created", "created", "skipped", "rejected"]
    assert body["counts"] == {"created": 2, "skipped": 1, "rejected": 1}

    for line in (2, 3):
        pid = rows[line]["playerId"]
        affiliation = db.query(PlayerOrganization).filter_by(player_id=pid).one()
        assert affiliation.organization_id == world["orgs"]["a"].id
        assert db.query(Consent).filter_by(player_id=pid).count() == 3
    # This test's own academy: the local database may hold real imports from other runs.
    audit = (
        db.query(AuditLog)
        .filter_by(action="players.import", entity_id=world["orgs"]["a"].id)
        .one()
    )
    assert audit.event_metadata["created"] == 2
    assert audit.event_metadata["skipped_unconfirmed_lines"] == [4]


def test_a_file_problem_saves_nothing(client, auth, world, db):
    from app.models.player import Player

    before = db.query(Player).count()
    text = _csv(_row(), header=HEADER + ",shoe_size")
    response = client.post("/players/import", json={"csv": text}, headers=auth("coach_a"))
    assert response.status_code == 422
    assert "shoe_size" in " ".join(response.json()["detail"]["problems"])
    assert db.query(Player).count() == before


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", "empty"),
        (HEADER + "\n", "no players"),
        ("full_name,sport\nA,football\n", "Missing required"),
    ],
)
def test_file_level_problems_are_said_plainly(client, auth, world, text, expected):
    body = _preview(client, auth, text).json()
    assert body["rows"] == []
    assert expected in " ".join(body["fileProblems"])


def test_too_many_rows_is_refused(client, auth, world):
    from app.services import imports

    text = _csv(*[_row(name=f"Player Test {i}") for i in range(imports.MAX_ROWS + 1)])
    body = _preview(client, auth, text).json()
    assert "More than" in body["fileProblems"][0]


def test_a_semicolon_file_from_excel_is_read(client, auth, world):
    text = _csv(_row().replace(",", ";"), header=HEADER.replace(",", ";"))
    rows = _by_line(_preview(client, auth, text).json())
    assert rows[2]["status"] == "ready"


@pytest.mark.parametrize("who", ["scout", "federation", "player_self"])
def test_only_coaches_and_admins_import(client, auth, world, who):
    assert _preview(client, auth, _csv(_row()), who=who).status_code == 403
