"""Test fixtures for the API.

These tests need a real PostgreSQL. The models use JSONB, ARRAY and `gen_random_uuid()`,
none of which SQLite provides, and faking them would mean testing a different schema from the
one that runs. `docker compose -f docker/docker-compose.yml up -d db` is enough. When no
database is reachable the whole suite skips with a message saying how to start one, rather
than failing with a connection error that looks like a broken test.

Each test runs inside a transaction that is rolled back afterwards, so the suite can be run
against a database that already holds the synthetic dataset without disturbing it.

The fixture builds its own small, known population rather than relying on whatever rows
happen to be present. The access-control assertions are about specific players with specific
consent states, and a test that depends on which player the generator happened to make a
minor is a test that fails for the wrong reason six months from now.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

DEFAULT_URL = "postgresql+psycopg://northstar:northstar@localhost:5432/northstar"
DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_URL)

# Everything the fixture creates is dated relative to this, so ages are stable whenever the
# suite runs.
TODAY = date.today()


def _engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True, future=True)


@pytest.fixture(scope="session")
def engine():
    engine = _engine()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(
            f"No database at {DATABASE_URL} ({type(exc).__name__}). Start one with:\n"
            f"  docker compose -f docker/docker-compose.yml up -d db"
        )
    return engine


@pytest.fixture
def db(engine) -> Session:
    """A session inside a transaction that is always rolled back."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db, monkeypatch):
    """A TestClient whose requests use the rolled-back session."""
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app
    from app.services import cohort

    # The cohort reference is cached per process and these tests insert new measurements
    # underneath it, so it has to be rebuilt rather than reused from another test.
    cohort.reset_cache()

    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        cohort.reset_cache()


# ---------------------------------------------------------------------------
# A small, known population
# ---------------------------------------------------------------------------


@pytest.fixture
def world(db):
    """Two academies, five players covering every access case, one user per role.

    The players are chosen to make each access rule falsifiable:

      adult_a       adult at academy A, visible to everyone
      minor_ok_a    minor at academy A WITH scouting consent
      minor_no_a    minor at academy A WITHOUT scouting consent
      adult_b       adult at academy B, outside coach A's scope
      minor_no_b    minor at academy B without consent
    """
    from app.models.consent import Consent
    from app.models.enums import (
        ConsentPurpose,
        FootballTier,
        MeasurementConfidence,
        MeasurementSource,
        OrganizationType,
        PlayerOrganizationRole,
        PlayerSex,
        Sport,
        UserRole,
    )
    from app.models.measurement import Measurement
    from app.models.organization import Organization
    from app.models.player import Player
    from app.models.player_organization import PlayerOrganization
    from app.models.user import User

    def org(name: str) -> Organization:
        row = Organization(
            id=uuid.uuid4(),
            name=name,
            type=OrganizationType.ACADEMY.value,
            sport=Sport.FOOTBALL.value,
            country="EG",
        )
        db.add(row)
        return row

    academy_a, academy_b = org("Test Academy A"), org("Test Academy B")
    db.flush()

    def player(name: str, *, age: float, minor: bool, organization: Organization) -> Player:
        row = Player(
            id=uuid.uuid4(),
            full_name=name,
            date_of_birth=TODAY - timedelta(days=int(age * 365.25)),
            sex=PlayerSex.MALE.value,
            nationality=["EG"],
            is_egypt_eligible=True,
            primary_sport=Sport.FOOTBALL.value,
            tier=(FootballTier.YOUTH if minor else FootballTier.PRO).value,
            position="ST",
            is_minor=minor,
            status="active",
        )
        db.add(row)
        db.flush()
        db.add(
            PlayerOrganization(
                id=uuid.uuid4(),
                player_id=row.id,
                organization_id=organization.id,
                role=PlayerOrganizationRole.PLAYER.value,
                start_date=TODAY - timedelta(days=400),
                end_date=None,
            )
        )
        # Enough height history for a trend, a velocity and a percentile.
        for index in range(6):
            db.add(
                Measurement(
                    id=uuid.uuid4(),
                    player_id=row.id,
                    measured_at=TODAY - timedelta(days=330 - index * 60),
                    metric="height_cm",
                    value=150 + index * 2,
                    unit="cm",
                    source=MeasurementSource.COACH_LOGGED.value,
                    confidence=MeasurementConfidence.MEASURED.value,
                )
            )
        return row

    people = {
        "adult_a": player("Adult A", age=24, minor=False, organization=academy_a),
        "minor_ok_a": player("Minor Consented A", age=15, minor=True, organization=academy_a),
        "minor_no_a": player("Minor Blocked A", age=15, minor=True, organization=academy_a),
        "adult_b": player("Adult B", age=24, minor=False, organization=academy_b),
        "minor_no_b": player("Minor Blocked B", age=14, minor=True, organization=academy_b),
    }

    def consent(player_row: Player, purpose: str, granted: bool) -> None:
        db.add(
            Consent(
                id=uuid.uuid4(),
                player_id=player_row.id,
                purpose=purpose,
                granted=granted,
                granted_by="guardian",
                guardian_name="Test Guardian",
                valid_from=TODAY - timedelta(days=365),
                valid_until=None,
            )
        )

    for person in people.values():
        consent(person, ConsentPurpose.DATA_STORAGE.value, True)
        consent(person, ConsentPurpose.ANALYTICS.value, True)
    consent(people["minor_ok_a"], ConsentPurpose.SCOUTING_VISIBILITY.value, True)
    consent(people["minor_no_a"], ConsentPurpose.SCOUTING_VISIBILITY.value, False)
    consent(people["adult_a"], ConsentPurpose.SCOUTING_VISIBILITY.value, True)
    consent(people["adult_b"], ConsentPurpose.SCOUTING_VISIBILITY.value, True)

    def user(role: str, organization: Organization | None, linked: Player | None = None) -> User:
        row = User(
            id=uuid.uuid4(),
            email=f"{role}.{uuid.uuid4().hex[:8]}@test.invalid",
            password_hash="not-a-real-hash",
            full_name=f"Test {role}",
            role=role,
            organization_id=organization.id if organization else None,
            linked_player_id=linked.id if linked else None,
            is_active=True,
        )
        db.add(row)
        return row

    users = {
        "coach_a": user(UserRole.COACH.value, academy_a),
        "coach_b": user(UserRole.COACH.value, academy_b),
        "coach_orphan": user(UserRole.COACH.value, None),
        "scout": user(UserRole.SCOUT.value, None),
        "federation": user(UserRole.FEDERATION.value, None),
        "admin": user(UserRole.ADMIN.value, None),
        "player_self": user(UserRole.PLAYER.value, academy_a, linked=people["adult_a"]),
    }
    inactive = user(UserRole.ADMIN.value, None)
    inactive.is_active = False
    users["inactive"] = inactive

    db.flush()
    from app.services import cohort

    cohort.reset_cache()
    return {
        "orgs": {"a": academy_a, "b": academy_b},
        "players": people,
        "users": users,
    }


@pytest.fixture
def auth(world):
    """Headers acting as a named user from `world`."""

    def _headers(who: str) -> dict[str, str]:
        return {"X-NorthStar-User": world["users"][who].email}

    return _headers
