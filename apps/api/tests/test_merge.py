"""Merging two records of one player on confirming a duplicate, and undoing it
(app/services/merge.py, routers/integrity.py).

The fixture players Adult A (academy A) and Adult B (academy B) stand in for one boy entered
twice. They share six height readings on the same days, which is the conflict case: the record
kept wins those, and the other's stay where they were.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.enums import FlagStatus, FlagType
from app.models.flag import Flag
from app.models.match_event import MatchEvent
from app.models.measurement import Measurement
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.models.player_organization import PlayerOrganization
from app.services import flags as flag_service
from tests.conftest import TODAY


@pytest.fixture
def case(db, world):
    """A duplicate case stored against Adult A, naming Adult B, and one reading only B has."""
    a, b = world["players"]["adult_a"], world["players"]["adult_b"]
    db.add(Measurement(
        id=uuid.uuid4(), player_id=b.id, measured_at=TODAY - timedelta(days=3),
        metric="height_cm", value=171, unit="cm", source="coach_logged",
    ))
    flag, _ = flag_service.upsert(
        db, player_id=a.id, flag_type=FlagType.DUPLICATE.value,
        reason="Likely the same player entered twice.", evidence={"points": []},
        detector_name="duplicate", detector_version="v1", fingerprint=f"pair:{uuid.uuid4()}",
        related_player_id=b.id,
    )
    db.flush()
    return flag


def _confirm(client, auth, flag, keep=None, who="federation"):
    body = {"decision": "confirmed", "reason": "Same boy, spoke to both academies."}
    if keep is not None:
        body["keepPlayerId"] = str(keep)
    return client.post(f"/integrity/flags/{flag.id}/decision", json=body, headers=auth(who))


def _undo(client, auth, merged_id, who="federation"):
    return client.post(
        f"/integrity/merges/{merged_id}/undo", json={"reason": "Two different boys after all."},
        headers=auth(who),
    )


def _heights(db, player_id):
    return sorted(
        (m.measured_at, float(m.value))
        for m in db.execute(
            select(Measurement).where(Measurement.player_id == player_id)
            .where(Measurement.metric == "height_cm")
        ).scalars()
    )


def test_confirming_a_duplicate_merges_into_the_record_with_more_history(client, auth, db, world, case):
    a, b = world["players"]["adult_a"], world["players"]["adult_b"]
    assert _confirm(client, auth, case).status_code == 200
    db.expire_all()

    # B has one more reading, so B is kept.
    assert db.get(Player, a.id).status == "merged"
    assert db.get(Player, a.id).merged_into == b.id
    assert db.get(Player, b.id).status == "active"
    assert db.get(Flag, case.id).status == FlagStatus.CONFIRMED.value
    # Same metric, same day: B's own readings win and A's stay behind on A.
    assert len(_heights(db, b.id)) == 7
    assert len(_heights(db, a.id)) == 6


def test_the_reviewer_may_choose_the_record_to_keep(client, auth, db, world, case):
    a, b = world["players"]["adult_a"], world["players"]["adult_b"]
    assert _confirm(client, auth, case, keep=a.id).status_code == 200
    db.expire_all()
    assert db.get(Player, b.id).merged_into == a.id
    # The one reading only B had moved to A; the six clashing ones stayed on B.
    assert (TODAY - timedelta(days=3), 171.0) in _heights(db, a.id)
    assert len(_heights(db, b.id)) == 6


def test_everything_else_moves_and_both_academies_keep_him(client, auth, db, world, case):
    """Matches, the opponent side of other players' matches, tagged events, the academy link
    and a linked account all follow the record kept."""
    a, b = world["players"]["adult_a"], world["players"]["adult_b"]
    other = world["players"]["minor_ok_a"]
    entry = PerformanceEntry(
        id=uuid.uuid4(), player_id=a.id, sport="football", period_type="match",
        period_start=TODAY - timedelta(days=9), metrics={"minutes_played": 90},
        schema_ref="football@1", source="coach_logged",
    )
    against = PerformanceEntry(
        id=uuid.uuid4(), player_id=other.id, sport="football", period_type="match",
        period_start=TODAY - timedelta(days=9), metrics={"minutes_played": 60},
        schema_ref="football@1", source="coach_logged", opponent_player_id=a.id,
    )
    event = MatchEvent(
        id=uuid.uuid4(), player_id=a.id, sport="football", match_date=TODAY - timedelta(days=9),
        event_type="shot", outcome="goal", source="coach_tagged",
    )
    db.add_all([entry, against, event])
    db.flush()

    assert _confirm(client, auth, case, keep=b.id).status_code == 200
    db.expire_all()
    assert db.get(PerformanceEntry, entry.id).player_id == b.id
    assert db.get(PerformanceEntry, against.id).opponent_player_id == b.id
    assert db.get(MatchEvent, event.id).player_id == b.id
    open_links = {
        row.organization_id
        for row in db.execute(
            select(PlayerOrganization).where(PlayerOrganization.player_id == b.id)
        ).scalars()
    }
    assert open_links == {world["orgs"]["a"].id, world["orgs"]["b"].id}
    assert world["users"]["player_self"].linked_player_id == b.id

    # And both coaches see him in their squads.
    for coach in ("coach_a", "coach_b"):
        squad = {r["player"]["id"] for r in client.get("/players", headers=auth(coach)).json()}
        assert str(b.id) in squad and str(a.id) not in squad


def test_the_merged_record_leads_to_the_record_kept(client, auth, world, case):
    a, b = world["players"]["adult_a"], world["players"]["adult_b"]
    _confirm(client, auth, case, keep=b.id)
    response = client.get(f"/players/{a.id}/profile", headers=auth("scout"))
    assert response.status_code == 404
    assert response.json()["detail"]["mergedInto"] == str(b.id)

    profile = client.get(f"/players/{b.id}/profile", headers=auth("federation")).json()
    [record] = profile["mergedRecords"]
    assert record["id"] == str(a.id) and record["fullName"] == "Adult A"
    assert record["mergedOn"] == TODAY.isoformat() and record["undoable"] is True
    # A scout sees the history but cannot undo it.
    scout_view = client.get(f"/players/{b.id}/profile", headers=auth("scout")).json()
    assert scout_view["mergedRecords"][0]["undoable"] is False


def test_a_merged_record_points_nowhere_a_caller_may_not_go(client, auth, world, case):
    """The 404 says where the record went only to a caller who may open the record kept."""
    a, b = world["players"]["adult_a"], world["players"]["adult_b"]
    _confirm(client, auth, case, keep=a.id)
    # Both coaches keep him: academy B's link moved to the record kept.
    for coach in ("coach_a", "coach_b"):
        response = client.get(f"/players/{b.id}/profile", headers=auth(coach))
        assert response.json()["detail"]["mergedInto"] == str(a.id)
    # A coach with no academy can see nobody, so is told nothing.
    hidden = client.get(f"/players/{b.id}/profile", headers=auth("coach_orphan"))
    assert hidden.status_code == 404 and hidden.json()["detail"] == "No such player."


def test_undo_puts_everything_back_exactly(client, auth, db, world, case):
    a, b = world["players"]["adult_a"], world["players"]["adult_b"]
    before = {pid: _heights(db, pid) for pid in (a.id, b.id)}
    _confirm(client, auth, case, keep=a.id)

    assert _undo(client, auth, b.id).status_code == 204
    db.expire_all()
    assert db.get(Player, b.id).status == "active" and db.get(Player, b.id).merged_into is None
    assert {pid: _heights(db, pid) for pid in (a.id, b.id)} == before
    assert db.get(PlayerOrganization, _link(db, b.id)).player_id == b.id
    # The case is open again, with the undo and its reason in its history.
    assert db.get(Flag, case.id).status == FlagStatus.OPEN.value
    row = next(f for f in client.get("/integrity/flags", headers=auth("federation")).json()
               if f["id"] == str(case.id))
    # (Every event in one test transaction has the same time, so the order is not checked.)
    assert "reopened, merge undone: Two different boys after all." in [
        h["what"] for h in row["history"]
    ]


def _link(db, player_id):
    return db.execute(
        select(PlayerOrganization.id).where(PlayerOrganization.player_id == player_id)
    ).scalars().first()


def test_merge_and_undo_are_audited(client, auth, db, world, case):
    a, b = world["players"]["adult_a"], world["players"]["adult_b"]
    _confirm(client, auth, case, keep=a.id)
    _undo(client, auth, b.id)
    actions = [
        row.action for row in db.execute(
            select(AuditLog).where(AuditLog.entity_id == b.id).order_by(AuditLog.created_at)
        ).scalars()
    ]
    assert actions == ["player.merge", "player.unmerge"]
    merge_row = db.execute(
        select(AuditLog).where(AuditLog.action == "player.merge").where(AuditLog.entity_id == b.id)
    ).scalar_one()
    assert merge_row.event_metadata["kept"] == str(a.id)
    assert len(merge_row.event_metadata["moved"]["measurement"]) == 1


@pytest.mark.parametrize("who", ["coach_a", "scout"])
def test_only_reviewers_merge_or_undo(client, auth, world, case, who):
    assert _confirm(client, auth, case, who=who).status_code == 403
    assert _undo(client, auth, world["players"]["adult_b"].id, who=who).status_code == 403


def test_a_record_to_keep_from_outside_the_case_is_refused(client, auth, db, world, case):
    response = _confirm(client, auth, case, keep=world["players"]["minor_ok_a"].id)
    assert response.status_code == 409
    db.expire_all()
    assert db.get(Flag, case.id).status == FlagStatus.OPEN.value
    assert db.get(Player, world["players"]["adult_a"].id).status == "active"


def test_records_of_different_genders_are_not_merged(client, auth, db, world, case):
    world["players"]["adult_b"].sex = "female"
    db.flush()
    assert _confirm(client, auth, case).status_code == 409


def test_undoing_a_record_that_is_not_merged_is_refused(client, auth, world):
    assert _undo(client, auth, world["players"]["adult_b"].id).status_code == 409


def test_other_open_cases_on_the_merged_record_close_and_reopen_with_undo(client, auth, db, world, case):
    a, b = world["players"]["adult_a"], world["players"]["adult_b"]
    fraud, _ = flag_service.upsert(
        db, player_id=b.id, flag_type=FlagType.FRAUD.value, reason="Test.", evidence={},
        detector_name="test", detector_version="v1",
    )
    db.flush()
    _confirm(client, auth, case, keep=a.id)
    db.expire_all()
    assert db.get(Flag, fraud.id).status == FlagStatus.DISMISSED.value
    _undo(client, auth, b.id)
    db.expire_all()
    assert db.get(Flag, fraud.id).status == FlagStatus.OPEN.value


def test_dismissing_a_duplicate_merges_nothing(client, auth, db, world, case):
    response = client.post(
        f"/integrity/flags/{case.id}/decision",
        json={"decision": "dismissed", "reason": "Twins, checked with the academy."},
        headers=auth("federation"),
    )
    assert response.status_code == 200
    db.expire_all()
    assert db.get(Player, world["players"]["adult_a"].id).status == "active"
    assert db.get(Player, world["players"]["adult_b"].id).status == "active"


def test_a_match_between_the_two_records_is_not_turned_into_one_against_himself(
    client, auth, db, world
):
    from tests.test_results_import import _tt_player

    a = _tt_player(db, world["orgs"]["a"], "Test Twice Registered")
    b = _tt_player(db, world["orgs"]["b"], "Test Twice")
    rows = [
        PerformanceEntry(
            id=uuid.uuid4(), player_id=me, sport="table_tennis", period_type="match",
            period_start=TODAY - timedelta(days=5), opponent_player_id=them,
            metrics={"sets_won": won, "sets_lost": 3 - won}, schema_ref="table_tennis@1",
            source="import",
        )
        for me, them, won in ((a.id, b.id, 3), (b.id, a.id, 0))
    ]
    db.add_all(rows)
    flag, _ = flag_service.upsert(
        db, player_id=a.id, flag_type=FlagType.DUPLICATE.value, reason="Test.", evidence={},
        detector_name="duplicate", detector_version="v1", related_player_id=b.id,
    )
    db.flush()
    assert _confirm(client, auth, flag, keep=a.id).status_code == 200
    db.expire_all()
    for row in rows:
        moved = db.get(PerformanceEntry, row.id)
        assert moved.player_id != moved.opponent_player_id
