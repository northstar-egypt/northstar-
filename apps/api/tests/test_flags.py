"""Flags: the table, the integrity board, and the rules around deciding.

The two behaviours with the most riding on them, and the reason the team chose this shape:

  **A dismissal sticks across a detector rerun.** With the detectors at 0.6 to 0.8 precision,
  a nightly job that re-raises every dismissed false positive is how a review queue gets
  abandoned. `dedupe_key` is what prevents it, and several tests here exist to stop that key
  becoming either too specific (dismissals stop working) or too coarse (genuinely new evidence
  gets swallowed by an old dismissal).

  **A decision is never recorded without a reason.** Each decision plus its reason is a
  labelled example, and labelled examples are what the detectors' precision and recall are
  computed from. A dismissal with no reason teaches nothing.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import FlagStatus, FlagType
from app.models.flag import Flag, FlagEvent
from app.services import flags as flag_service


@pytest.fixture(autouse=True)
def isolated_flags(db):
    """Start every test in this file with an empty flag table.

    Unlike players, flags are not scoped to the fixture's own world: several tests here assert
    on counts across the whole database, and a developer who has run `python -m ml.write_flags`
    against their local Postgres has 38 real flags sitting in it. Without this the suite passes
    on a clean machine and fails on a working one, which is the worst kind of test.

    Safe because the surrounding transaction is rolled back, so the real rows come back
    afterwards.
    """
    db.query(FlagEvent).delete()
    db.query(Flag).delete()
    db.flush()


@pytest.fixture
def raise_flag(db, world):
    """Raise a flag against one of the fixture players."""

    def _raise(
        who: str = "adult_a",
        flag_type: str = FlagType.FRAUD.value,
        *,
        fingerprint: str = "",
        reason: str = "Test reason, long enough to be a sentence.",
        confidence: float | None = 0.8,
        related: str | None = None,
        evidence: dict | None = None,
    ) -> tuple[Flag, bool]:
        flag, created = flag_service.upsert(
            db,
            player_id=world["players"][who].id,
            flag_type=flag_type,
            reason=reason,
            evidence=evidence or {"points": ["one", "two"]},
            detector_name="test_detector",
            detector_version="v1",
            fingerprint=fingerprint,
            confidence=confidence,
            related_player_id=world["players"][related].id if related else None,
        )
        return flag, created

    return _raise


# ---------------------------------------------------------------------------
# dedupe_key
# ---------------------------------------------------------------------------


def test_the_same_case_is_raised_once(raise_flag):
    first, created_first = raise_flag()
    second, created_second = raise_flag()
    assert created_first is True
    assert created_second is False
    assert first.id == second.id


def test_a_different_fingerprint_is_a_different_case(raise_flag):
    """Materially new evidence must be able to raise a new flag.

    Otherwise a single dismissal would silence every future finding of that type about that
    player, which is how a dedupe key turns into a way to hide things.
    """
    first, _ = raise_flag(fingerprint="rows:1,2")
    second, created = raise_flag(fingerprint="rows:7,8")
    assert created is True
    assert first.id != second.id


def test_the_key_ignores_confidence_so_drift_does_not_split_a_case(raise_flag):
    """Ordinary rerun-to-rerun wobble in a score is not new evidence."""
    first, _ = raise_flag(confidence=0.71)
    second, created = raise_flag(confidence=0.83)
    assert created is False
    assert first.id == second.id


def test_the_key_is_stable_whether_the_id_is_a_uuid_or_a_string():
    """The detector run passes ids as strings; the API has UUID objects. Same case."""
    player_id = uuid.uuid4()
    assert flag_service.make_dedupe_key(
        player_id, "fraud", "x"
    ) == flag_service.make_dedupe_key(str(player_id), "fraud", "x")


def test_reraising_an_open_case_refreshes_its_wording_but_not_its_history(db, raise_flag):
    """A detector may phrase the same claim better next time. That is not a new case."""
    first, _ = raise_flag(reason="First phrasing of the claim.")
    again, created = raise_flag(reason="Second, clearer phrasing of the same claim.")
    assert created is False
    assert again.reason == "Second, clearer phrasing of the same claim."
    events = db.query(FlagEvent).filter(FlagEvent.flag_id == first.id).all()
    assert len(events) == 1, "re-raising must not append a second raised event"


def test_a_dismissed_case_is_not_raised_again(db, raise_flag, world):
    """The whole point. A reviewer who rejects a false positive is not handed it tomorrow."""
    flag, _ = raise_flag()
    flag_service.decide(
        db,
        flag=flag,
        decision=FlagStatus.DISMISSED.value,
        reason="Checked the source documents, the detector was wrong.",
        actor_user_id=world["users"]["federation"].id,
    )

    same, created = raise_flag()
    assert created is False
    assert same.id == flag.id
    assert same.status == FlagStatus.DISMISSED.value


def test_a_dismissed_case_keeps_its_wording_untouched(db, raise_flag, world):
    """Only open cases are refreshed. Rewriting a decided case would rewrite the record."""
    flag, _ = raise_flag(reason="Original claim.")
    flag_service.decide(
        db,
        flag=flag,
        decision=FlagStatus.DISMISSED.value,
        reason="Not a real case.",
        actor_user_id=world["users"]["federation"].id,
    )
    again, _ = raise_flag(reason="Rewritten claim.")
    assert again.reason == "Original claim."


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def test_raising_writes_a_system_event(db, raise_flag):
    flag, _ = raise_flag()
    events = db.query(FlagEvent).filter(FlagEvent.flag_id == flag.id).all()
    assert len(events) == 1
    assert events[0].action == "raised"
    assert events[0].actor_user_id is None, "a detector is not a person"


def test_deciding_appends_rather_than_overwriting(db, raise_flag, world):
    flag, _ = raise_flag()
    reviewer = world["users"]["federation"].id
    flag_service.decide(
        db, flag=flag, decision="needs_info", reason="Asked the club for the match sheets.",
        actor_user_id=reviewer,
    )
    flag_service.decide(
        db, flag=flag, decision="confirmed", reason="Club confirmed the dates were wrong.",
        actor_user_id=reviewer,
    )

    events = (
        db.query(FlagEvent)
        .filter(FlagEvent.flag_id == flag.id)
        .order_by(FlagEvent.created_at)
        .all()
    )
    assert [event.action for event in events] == ["raised", "needs_info", "confirmed"]
    assert flag.status == "confirmed"
    # The earlier decision and its reason survive. That is the point of an append-only log.
    assert any("match sheets" in (event.reason or "") for event in events)


# ---------------------------------------------------------------------------
# Reads on the profile and squad screens
# ---------------------------------------------------------------------------


def test_flags_appear_on_the_player_profile(client, auth, world, raise_flag):
    raise_flag("adult_a", reason="Body and recorded age disagree.")
    player_id = world["players"]["adult_a"].id
    body = client.get(f"/players/{player_id}/profile", headers=auth("coach_a")).json()
    assert [flag["type"] for flag in body["flags"]] == ["fraud"]
    assert body["flagReason"] == "Body and recorded age disagree."


def test_flags_are_withheld_from_a_player_looking_at_themselves(
    client, auth, world, raise_flag
):
    """Access control, not presentation.

    The permissions object already says canSeeFlags is false for a player on their own
    record. This asserts the API does not *send* them anyway and leave the browser to hide
    them, which would make the flag readable by anyone opening devtools.
    """
    raise_flag("adult_a")
    player_id = world["players"]["adult_a"].id
    body = client.get(f"/players/{player_id}/profile", headers=auth("player_self")).json()
    assert body["permissions"]["canSeeFlags"] is False
    assert body["flags"] == []
    assert body["flagReason"] is None


def test_dismissed_flags_do_not_show_on_the_profile(client, auth, world, raise_flag, db):
    flag, _ = raise_flag("adult_a")
    flag_service.decide(
        db, flag=flag, decision=FlagStatus.DISMISSED.value, reason="Reviewed and rejected.",
        actor_user_id=world["users"]["federation"].id,
    )
    player_id = world["players"]["adult_a"].id
    body = client.get(f"/players/{player_id}/profile", headers=auth("coach_a")).json()
    assert body["flags"] == []


def test_flags_appear_on_the_squad_table(client, auth, world, raise_flag):
    raise_flag("minor_ok_a", flag_type=FlagType.LATE_BLOOMER.value)
    rows = {
        row["player"]["fullName"]: row
        for row in client.get("/players", headers=auth("coach_a")).json()
    }
    assert [flag["type"] for flag in rows["Minor Consented A"]["flags"]] == ["late_bloomer"]
    assert rows["Minor Consented A"]["flags"][0]["label"] == "late bloomer"
    assert rows["Adult A"]["flags"] == []


# ---------------------------------------------------------------------------
# The integrity board
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "who,expected", [("federation", 200), ("admin", 200), ("scout", 403), ("coach_a", 403)]
)
def test_the_board_is_limited_to_reviewers(client, auth, who, expected):
    assert client.get("/integrity/flags", headers=auth(who)).status_code == expected


def test_a_non_reviewer_is_refused_before_their_body_is_validated(client, auth, world):
    """403 whatever they send.

    Checked as a dependency rather than inside the handler, so an unauthorised caller does
    not get a 422 explaining what was wrong with the body they were not allowed to post.
    """
    flag_id = uuid.uuid4()
    response = client.post(
        f"/integrity/flags/{flag_id}/decision", json={}, headers=auth("scout")
    )
    assert response.status_code == 403


def test_the_board_carries_late_bloomers_nowhere_near_it(client, auth, raise_flag):
    """A late bloomer is not an integrity concern and would only be noise in a review queue."""
    raise_flag("adult_a", flag_type=FlagType.LATE_BLOOMER.value)
    raise_flag("adult_b", flag_type=FlagType.FRAUD.value)
    types = {
        row["type"] for row in client.get("/integrity/flags", headers=auth("federation")).json()
    }
    assert "late_bloomer" not in types
    assert "fraud" in types


def test_a_board_row_carries_its_evidence_and_history(client, auth, raise_flag):
    raise_flag(
        "adult_a",
        reason="Self-submitted rows do not add up.",
        evidence={"points": ["more goals than shots", "all submitted in one session"]},
    )
    row = next(
        row
        for row in client.get("/integrity/flags", headers=auth("federation")).json()
        if row["type"] == "fraud"
    )
    assert row["evidence"] == ["more goals than shots", "all submitted in one session"]
    assert row["history"][0]["who"] == "system"
    assert "raised" in row["history"][0]["what"]
    assert row["playerName"] == "Adult A"


def test_a_duplicate_flag_carries_the_field_by_field_diff(client, auth, raise_flag):
    """For a duplicate this diff is the whole decision, and it has to show which record has
    more history, because that determines which one survives the merge."""
    raise_flag("adult_a", flag_type=FlagType.DUPLICATE.value, related="adult_b")
    row = next(
        row
        for row in client.get("/integrity/flags", headers=auth("federation")).json()
        if row["type"] == "duplicate"
    )
    assert row["records"] is not None
    fields = {field["field"]: field for field in row["records"]["fields"]}
    assert fields["Full name"]["a"] == "Adult A"
    assert fields["Full name"]["b"] == "Adult B"
    assert fields["Full name"]["differs"] is True
    assert "Measurements" in fields


def test_a_non_duplicate_flag_has_no_diff(client, auth, raise_flag):
    raise_flag("adult_a", flag_type=FlagType.FRAUD.value)
    row = next(
        row
        for row in client.get("/integrity/flags", headers=auth("federation")).json()
        if row["type"] == "fraud"
    )
    assert row["records"] is None


def test_the_board_defaults_to_open_cases(client, auth, world, raise_flag, db):
    flag, _ = raise_flag("adult_a")
    raise_flag("adult_b", flag_type=FlagType.DUPLICATE.value, related="adult_a")
    flag_service.decide(
        db, flag=flag, decision=FlagStatus.DISMISSED.value, reason="Rejected on review.",
        actor_user_id=world["users"]["federation"].id,
    )

    open_rows = client.get("/integrity/flags", headers=auth("federation")).json()
    assert {row["type"] for row in open_rows} == {"duplicate"}

    dismissed = client.get(
        "/integrity/flags?status=dismissed", headers=auth("federation")
    ).json()
    assert {row["type"] for row in dismissed} == {"fraud"}


def test_the_board_rejects_an_unknown_status(client, auth):
    response = client.get("/integrity/flags?status=banana", headers=auth("federation"))
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Deciding through the API
# ---------------------------------------------------------------------------


def test_a_decision_records_who_what_and_why(client, auth, world, raise_flag, db):
    flag, _ = raise_flag("adult_a")
    db.commit()

    response = client.post(
        f"/integrity/flags/{flag.id}/decision",
        json={
            "decision": "confirmed",
            "reason": "Checked the birth certificate against the federation record.",
        },
        headers=auth("federation"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"
    assert any("birth certificate" in entry["what"] for entry in body["history"])
    assert any(entry["who"] == "Test federation" for entry in body["history"])


def test_a_decision_without_a_reason_is_refused(client, auth, raise_flag, db):
    """Not bureaucracy: a decision plus its reason is a labelled example."""
    flag, _ = raise_flag("adult_a")
    db.commit()
    response = client.post(
        f"/integrity/flags/{flag.id}/decision",
        json={"decision": "dismissed", "reason": ""},
        headers=auth("federation"),
    )
    assert response.status_code == 422


def test_an_unknown_decision_is_refused(client, auth, raise_flag, db):
    flag, _ = raise_flag("adult_a")
    db.commit()
    response = client.post(
        f"/integrity/flags/{flag.id}/decision",
        json={"decision": "probably_fine", "reason": "Looks alright to me honestly."},
        headers=auth("federation"),
    )
    assert response.status_code == 400


def test_deciding_a_flag_that_does_not_exist(client, auth):
    response = client.post(
        f"/integrity/flags/{uuid.uuid4()}/decision",
        json={"decision": "dismissed", "reason": "This flag does not exist."},
        headers=auth("federation"),
    )
    assert response.status_code == 404


def test_a_decision_writes_an_audit_row(client, auth, world, raise_flag, db):
    from app.models.audit_log import AuditLog

    flag, _ = raise_flag("adult_a")
    db.commit()
    client.post(
        f"/integrity/flags/{flag.id}/decision",
        json={"decision": "dismissed", "reason": "Reviewed, the club explained the gap."},
        headers=auth("federation"),
    )
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "flag", AuditLog.entity_id == flag.id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].action == "flag.dismissed"
    assert rows[0].actor_user_id == world["users"]["federation"].id


# ---------------------------------------------------------------------------
# Oversight and merged records
# ---------------------------------------------------------------------------


def test_open_flags_reach_the_oversight_summary(client, auth, raise_flag):
    raise_flag("adult_a", flag_type=FlagType.FRAUD.value)
    raise_flag("adult_b", flag_type=FlagType.DUPLICATE.value, related="adult_a")
    # Not an integrity concern, so it must not inflate the number.
    raise_flag("minor_ok_a", flag_type=FlagType.LATE_BLOOMER.value)
    body = client.get("/oversight", headers=auth("federation")).json()
    assert body["openFlags"] == 2


def test_flags_against_merged_records_are_closed(db, raise_flag, world):
    """A merged record is no longer a player, so a flag on it cannot be actioned."""
    from app.models.enums import PlayerStatus

    flag, _ = raise_flag("adult_b")
    world["players"]["adult_b"].status = PlayerStatus.MERGED.value
    world["players"]["adult_b"].merged_into = world["players"]["adult_a"].id
    db.flush()

    closed = flag_service.purge_merged_player_flags(db)
    assert closed == 1
    assert db.get(Flag, flag.id).status == FlagStatus.DISMISSED.value
