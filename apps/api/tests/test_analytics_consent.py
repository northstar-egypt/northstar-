"""Withdrawn analytics consent reaches every analytic on the platform.

A guardian signs one form at sign-up covering storage, analytics and scouting visibility, and
can withdraw any part of it later. Once analytics consent is withdrawn, nothing that ranks,
scores or flags the child as a talent may use their data, and their data may not be used to
rank anyone else either. The rating and the height forecast have their own tests; this file
covers the rest:

- the profile's percentile bars (none, and the screen says why),
- the cohorts everyone else's percentiles are computed against,
- talent flags (late bloomer, breakout), while integrity flags stay visible,
- every search concept, and the statistics table the stat concepts rank against.

There is no withdrawal endpoint yet, so the tests flip the consent row the way one would.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.models.enums import FlagType
from app.services import flags as flag_service
from tests.conftest import TODAY, grant_analytics, withdraw_analytics


@pytest.fixture
def cohort_of_boys(db, world):
    """Ten consented boys of 15 measured today, so a 15-year-old's cohort is never too small,
    plus one far taller than anyone, whose reading is easy to find in the reference."""
    from app.models.measurement import Measurement
    from app.models.player import Player
    from app.services import cohort

    def boy(name: str, height: float) -> Player:
        row = Player(
            id=uuid.uuid4(),
            full_name=name,
            date_of_birth=TODAY - timedelta(days=int(15.2 * 365.25)),
            sex="male",
            nationality=["EG"],
            is_egypt_eligible=True,
            primary_sport="football",
            tier="youth",
            position="CM",
            is_minor=True,
            status="active",
        )
        db.add(row)
        db.flush()
        grant_analytics(db, row)
        db.add(
            Measurement(
                id=uuid.uuid4(),
                player_id=row.id,
                measured_at=TODAY,
                metric="height_cm",
                value=height,
                unit="cm",
                source="coach_logged",
            )
        )
        return row

    boys = [boy(f"Cohort Boy {i}", 150 + i * 3) for i in range(10)]
    tallest = boy("Very Tall Boy", 231.7)
    db.flush()
    cohort.reset_cache()
    return {"boys": boys, "tallest": tallest}


def _profile(client, auth, player) -> dict:
    return client.get(f"/players/{player.id}/profile", headers=auth("admin")).json()


def _search_ids(client, auth, query: str) -> set[str]:
    body = client.post(
        "/search",
        json={"query": query, "limit": 200, "includeMinors": True},
        headers=auth("admin"),
    ).json()
    return {r["player"]["id"] for r in body["results"]}


# ---------------------------------------------------------------------------
# Percentiles
# ---------------------------------------------------------------------------


def test_a_withdrawn_player_gets_no_percentiles_and_is_told_why(
    client, auth, db, cohort_of_boys
):
    player = cohort_of_boys["boys"][4]
    before = _profile(client, auth, player)
    assert before["percentiles"], "a consented boy in a full cohort has a height percentile"
    assert before["percentilesNote"] is None

    withdraw_analytics(db, player)
    after = _profile(client, auth, player)
    assert after["percentiles"] == []
    assert "analytics consent" in after["percentilesNote"]


def test_a_withdrawn_players_readings_leave_everyone_elses_cohort(db, cohort_of_boys):
    """Ranking the other boys against his height is analytics on his data too. The cached
    reference notices the consent change on the next read, without waiting for its TTL."""
    from app.services import cohort

    def tall_reading_in_reference() -> bool:
        reference = cohort.get_reference(db)
        return 231.7 in reference.observations("height_cm", "male", 15.2)

    assert tall_reading_in_reference()
    withdraw_analytics(db, cohort_of_boys["tallest"])
    assert not tall_reading_in_reference()


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


def _raise(db, player, flag_type: str, reason: str, confidence: float):
    flag_service.upsert(
        db,
        player_id=player.id,
        flag_type=flag_type,
        reason=reason,
        evidence={"points": ["one"]},
        detector_name="test_detector",
        detector_version="v1",
        confidence=confidence,
    )
    db.flush()


def test_talent_flags_are_hidden_and_integrity_flags_stay(client, auth, db, world):
    """A late-bloomer flag is talent analytics, so it goes. A fraud flag protects the platform
    and other children, and withdrawing analytics consent must not hide it from review."""
    player = world["players"]["minor_ok_a"]
    _raise(db, player, FlagType.LATE_BLOOMER.value, "Growing late, catching up fast.", 0.9)
    _raise(db, player, FlagType.FRAUD.value, "Body and recorded age disagree.", 0.6)

    before = _profile(client, auth, player)
    assert {f["type"] for f in before["flags"]} == {"late_bloomer", "fraud"}
    assert before["flagReason"] == "Growing late, catching up fast."

    withdraw_analytics(db, player)
    after = _profile(client, auth, player)
    assert [f["type"] for f in after["flags"]] == ["fraud"]
    # The banner's sentence comes from the highest-confidence flag still shown, not from the
    # hidden one.
    assert after["flagReason"] == "Body and recorded age disagree."

    squad = {
        row["player"]["fullName"]: row
        for row in client.get("/players", headers=auth("coach_a")).json()
    }
    assert [f["type"] for f in squad["Minor Consented A"]["flags"]] == ["fraud"]


def test_a_hidden_talent_flag_is_kept_not_deleted(db, world):
    """Consent can be given again, and the flag's history is the detectors' training signal,
    so hiding is a read rule, not a delete."""
    from app.models.flag import Flag

    player = world["players"]["minor_ok_a"]
    _raise(db, player, FlagType.LATE_BLOOMER.value, "Growing late, catching up fast.", 0.9)
    withdraw_analytics(db, player)
    assert flag_service.flags_for_player(db, player.id) == []
    assert db.query(Flag).filter_by(player_id=player.id, type="late_bloomer").count() == 1


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_a_body_concept_stops_matching_a_withdrawn_player(client, auth, db, cohort_of_boys):
    tallest = str(cohort_of_boys["tallest"].id)
    assert tallest in _search_ids(client, auth, "tall for his age")
    withdraw_analytics(db, cohort_of_boys["tallest"])
    assert tallest not in _search_ids(client, auth, "tall for his age")


def test_a_late_bloomer_search_stops_matching_a_withdrawn_player(client, auth, db, world):
    player = world["players"]["minor_ok_a"]
    _raise(db, player, FlagType.LATE_BLOOMER.value, "Growing late, catching up fast.", 0.9)
    assert str(player.id) in _search_ids(client, auth, "late bloomer")
    withdraw_analytics(db, player)
    assert str(player.id) not in _search_ids(client, auth, "late bloomer")


def test_a_withdrawn_players_matches_leave_the_statistics_table(db):
    """The stat concepts rank players against everyone in the same kind of record. A child
    without analytics consent is not in that population."""
    from app.models.performance_entry import PerformanceEntry
    from app.models.player import Player
    from app.services import concept_filter

    row = Player(
        id=uuid.uuid4(),
        full_name="Stats Table Player",
        date_of_birth=TODAY - timedelta(days=int(15.5 * 365.25)),
        sex="male",
        nationality=["EG"],
        is_egypt_eligible=True,
        primary_sport="table_tennis",
        position="chopper",
        is_minor=True,
        status="active",
    )
    db.add(row)
    db.flush()
    grant_analytics(db, row)
    for week in range(3):
        db.add(
            PerformanceEntry(
                player_id=row.id,
                sport="table_tennis",
                period_type="match",
                period_start=TODAY - timedelta(weeks=week + 1),
                metrics={
                    "best_of": 5, "sets_won": 3, "sets_lost": 1,
                    "points_won": 44, "points_lost": 33,
                    "unforced_errors": 4, "service_winners": 6,
                },
                schema_ref="table_tennis.match.v1",
                source="coach_logged",
                is_validated=True,
            )
        )
    db.flush()
    concept_filter.reset_cache()

    def in_table() -> bool:
        return any(row.id in values for values in concept_filter._stat_table(db).values())

    assert in_table()
    withdraw_analytics(db, row)
    assert not in_table()
