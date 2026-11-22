"""Diaspora submissions (decision 0011; app/routers/submissions.py, app/services/submissions.py).

Invented players only. Names, clubs and leagues are made up, and the event names keep the
league seasons apart from anything else in the database.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, timedelta

import pytest

from tests.conftest import _add_player

TODAY = date.today()


def _payload(**changes):
    body = {
        "fullName": "Karim Adel Mansour", "dateOfBirth": (TODAY - timedelta(days=int(23 * 365.25))).isoformat(),
        "sex": "male", "nationality": ["EG", "DE"], "eligibilityBasis": "egyptian_nationality", "position": "ST",
        "clubName": "FC Invented Nord", "clubCountry": "DE", "competition": "Invented Liga",
        "sourceUrl": "https://example.org/fc-invented-nord/squad", "note": "",
        "seasons": [{"competition": "Invented Liga", "season": "2024/25", "metrics": {
            "position_group": "forward", "appearances": 28, "minutes_played": 2100, "goals": 9, "assists": 4,
            "penalty_goals": 1, "yellow_cards": 3, "red_cards": 0}}],
        "consent": {"signed": True},
    }
    body.update(changes)
    return body


def _minor_dob():
    return (TODAY - timedelta(days=int(16 * 365.25))).isoformat()


def _post(client, auth, who="scout", **changes):
    return client.post("/submissions", json=_payload(**changes), headers=auth(who))


def _created(client, auth, who="scout", **changes):
    response = _post(client, auth, who, **changes)
    assert response.status_code == 201, response.text
    return response.json()


def _check(body, key):
    return next(c for c in body["checks"] if c["key"] == key)


def _decide(client, auth, submission_id, action, who="federation", **extra):
    return client.post(f"/submissions/{submission_id}/decision", headers=auth(who),
                       json={"action": action, "reason": "Checked the club's squad page.", **extra})


@pytest.fixture(autouse=True)
def fresh_identity_model():
    """The identity model is kept between submissions while the player count holds steady. Each
    test has its own small set of players, so each fits its own."""
    from app.services import submissions

    submissions._FIT.clear()
    yield
    submissions._FIT.clear()


@pytest.fixture
def register(db, world):
    """200 invented players, so the identity engine has a population to learn from: it measures
    how often two different people agree by chance on random pairs of the records on hand, and
    the handful of players in `world` is too few for that (ml/identity/engine.py, `random_u`)."""
    rng = random.Random(4)
    first = ["Ahmed", "Omar", "Youssef", "Mostafa", "Ali", "Hassan", "Mahmoud", "Tarek", "Sherif", "Hany"]
    rest = ["Ibrahim", "Saleh", "Fathy", "Nabil", "Samir", "Gamal", "Lotfy", "Rashad", "Wahba", "Zaki"]
    for _ in range(200):
        _add_player(db, world["orgs"]["b"], f"{rng.choice(first)} {rng.choice(rest)} {rng.choice(rest)}",
                    age=rng.uniform(15, 30), position="ST", shots=1, n_matches=0)
    db.flush()


@pytest.fixture
def second_reviewer(db, world):
    """Another federation account, so a federation member's own submission can be decided."""
    from app.models.user import User
    from app.security import issue_token

    user = User(id=uuid.uuid4(), email=f"fed2.{uuid.uuid4().hex[:8]}@test.invalid", password_hash="x",
                full_name="Second Reviewer", role="federation", is_active=True)
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {issue_token(user.id)}"}


# ---------------------------------------------------------------------------
# Who may do what
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["coach_a", "admin"])
def test_only_scouts_players_and_federation_staff_submit(client, auth, world, who):
    assert _post(client, auth, who).status_code == 403


@pytest.mark.parametrize("who", ["scout", "coach_a", "admin", "player_self"])
def test_only_federation_staff_see_the_queue_and_decide(client, auth, world, who):
    submission = _created(client, auth)
    assert client.get("/submissions", headers=auth(who)).status_code == 403
    assert _decide(client, auth, submission["id"], "reject", who=who).status_code == 403


def test_a_submission_is_seen_by_its_submitter_and_federation_staff_only(client, auth, world):
    submission = _created(client, auth)
    assert client.get(f"/submissions/{submission['id']}", headers=auth("scout")).json()["mine"] is True
    assert client.get(f"/submissions/{submission['id']}", headers=auth("federation")).status_code == 200
    for who in ("coach_a", "player_self", "admin"):
        assert client.get(f"/submissions/{submission['id']}", headers=auth(who)).status_code == 404
    queue = client.get("/submissions", headers=auth("federation")).json()["submissions"]
    assert submission["id"] in [s["id"] for s in queue]
    assert [s["id"] for s in client.get("/submissions/mine", headers=auth("scout")).json()["submissions"]] == [
        submission["id"]]


def test_a_reviewer_cannot_decide_their_own_submission(client, auth, world, second_reviewer):
    submission = _created(client, auth, who="federation")
    assert _decide(client, auth, submission["id"], "approve").status_code == 403
    response = client.post(f"/submissions/{submission['id']}/decision", headers=second_reviewer,
                           json={"action": "reject", "reason": "Not the player the source shows."})
    assert response.status_code == 200 and response.json()["status"] == "rejected"


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------


def test_an_adult_with_the_form_signed_is_pending(client, auth, world):
    submission = _created(client, auth)
    assert submission["status"] == "pending" and submission["consent"]["signed"] is True


def test_without_the_form_the_submission_waits_for_consent(client, auth, world):
    assert _created(client, auth, consent=None)["status"] == "awaiting_consent"


def test_a_scout_cannot_record_consent_for_a_minor(client, auth, world):
    submission = _created(client, auth, dateOfBirth=_minor_dob(),
                          consent={"signed": True, "guardianName": "A Guardian"})
    assert submission["status"] == "awaiting_consent" and submission["isMinor"] is True
    # Nothing can be approved before the guardian's consent is recorded.
    assert _decide(client, auth, submission["id"], "approve").status_code == 422

    url = f"/submissions/{submission['id']}/consent"
    assert client.post(url, json={"signed": True}, headers=auth("federation")).status_code == 422
    assert client.post(url, json={"signed": True, "guardianName": "A Guardian"},
                       headers=auth("scout")).status_code == 403
    recorded = client.post(url, json={"signed": True, "guardianName": "A Guardian"}, headers=auth("federation"))
    assert recorded.status_code == 200 and recorded.json()["status"] == "pending"
    assert recorded.json()["consent"]["guardianName"] == "A Guardian"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("changes", "says"), [
    ({"clubCountry": "Germany"}, None),  # refused by the schema itself: two letters
    ({"clubCountry": "D1"}, "two-letter country code"),
    ({"sourceUrl": "the club's website, ask me"}, "web address"),
    ({"eligibilityBasis": "a feeling"}, "Eligibility basis"),
    ({"eligibilityBasis": "egyptian_nationality", "nationality": ["DE"]}, "EG is not among"),
    ({"eligibilityBasis": "other", "note": ""}, "needs the note"),
    ({"dateOfBirth": (TODAY + timedelta(days=3)).isoformat()}, "in the future"),
    ({"position": "Libero"}, "is not a position"),
    ({"seasons": [{"competition": "Invented Liga", "season": "2024/25", "metrics": {
        "position_group": "forward", "appearances": 10, "minutes_played": 900, "goals": 2, "assists": 1,
        "penalty_goals": 3, "yellow_cards": 0, "red_cards": 0}}]}, "more penalty goals than goals"),
    ({"seasons": [{"competition": "Invented Liga", "season": "24/25", "metrics": {}}]}, "not a season"),
])
def test_claims_that_cannot_be_stored_are_refused_with_the_reason(client, auth, world, changes, says):
    response = _post(client, auth, **changes)
    assert response.status_code == 422
    if says:
        assert any(says in p for p in response.json()["detail"]["problems"]), response.json()


# ---------------------------------------------------------------------------
# Checks on arrival
# ---------------------------------------------------------------------------


def test_a_player_already_on_record_is_found_and_a_different_birth_date_is_raised(client, auth, db, world,
                                                                                   register):
    org = world["orgs"]["a"]
    on_record = _add_player(db, org, "Karim Adel Mansour", age=23, position="ST", shots=1, n_matches=0)
    db.flush()

    same = _created(client, auth, dateOfBirth=on_record.date_of_birth.isoformat())
    identity = _check(same, "identity")
    assert identity["outcome"] == "attention"
    assert identity["matches"][0]["id"] == str(on_record.id) and identity["matches"][0]["probability"] >= 0.5
    assert _check(same, "date_of_birth")["outcome"] == "clear"

    # Born within a week: a typing slip, so a likely match.
    slip = _created(client, auth, dateOfBirth=(on_record.date_of_birth + timedelta(days=3)).isoformat())
    assert str(on_record.id) in [m["id"] for m in _check(slip, "identity")["matches"]]

    # Five months younger on paper: what an age-fraud re-registration looks like.
    younger = _created(client, auth, dateOfBirth=(on_record.date_of_birth + timedelta(days=150)).isoformat())
    dob = _check(younger, "date_of_birth")
    assert dob["outcome"] == "attention" and "age misrepresentation" in dob["summary"]
    assert dob["matches"][0]["id"] == str(on_record.id)
    # A brother shares everything but the given name: not raised.
    brother = _created(client, auth, fullName="Omar Adel Mansour",
                       dateOfBirth=(on_record.date_of_birth + timedelta(days=150)).isoformat())
    assert _check(brother, "date_of_birth")["outcome"] == "clear"


def test_an_unknown_player_is_clear(client, auth, world, register):
    submission = _created(client, auth, fullName="Zoltan Quetzal Brightwater")
    assert _check(submission, "identity")["outcome"] == "clear"


def test_a_player_submitting_themselves_is_matched_to_their_own_record(client, auth, world, register):
    submission = _created(client, auth, who="player_self", fullName="Somebody Else Entirely")
    matches = _check(submission, "identity")["matches"]
    assert matches[0]["id"] == str(world["players"]["adult_a"].id)
    assert "own account" in matches[0]["evidence"][0]


def _league(db, org, n):
    from app.models.performance_entry import PerformanceEntry

    for i in range(n):
        peer = _add_player(db, org, f"Submission Peer {i}", age=25, position=None, shots=1, n_matches=0)
        db.add(PerformanceEntry(
            id=uuid.uuid4(), player_id=peer.id, sport="football", period_type="season_aggregate",
            period_start=date(2024, 8, 1), period_end=date(2025, 5, 30), organization_id=org.id,
            event="Invented Liga 2024/25", schema_ref="football.season_basic.v1", source="footystats",
            is_validated=True, metrics={"position_group": "forward", "appearances": 25, "minutes_played": 2000,
                                        "goals": i % 10, "assists": i % 5, "penalty_goals": 0, "yellow_cards": 1,
                                        "red_cards": 0}))
    db.flush()


def test_numbers_above_every_player_of_the_league_are_raised(client, auth, db, world):
    _league(db, world["orgs"]["a"], 20)
    seasons = [{"competition": "Invented Liga", "season": "2024/25", "metrics": {
        "position_group": "forward", "appearances": 30, "minutes_played": 2700, "goals": 40, "assists": 2,
        "penalty_goals": 0, "yellow_cards": 0, "red_cards": 0}}]
    numbers = _check(_created(client, auth, seasons=seasons), "numbers")
    assert numbers["outcome"] == "attention" and "above every one of 20 forwards" in numbers["summary"]
    assert _check(_created(client, auth), "numbers")["outcome"] == "clear"


def test_with_too_few_players_on_record_the_numbers_are_not_compared(client, auth, db, world):
    _league(db, world["orgs"]["a"], 19)
    numbers = _check(_created(client, auth), "numbers")
    assert numbers["outcome"] == "not_run" and "19 forwards on record; 20 are needed" in numbers["summary"]


def test_the_submitter_check_counts_rejections(client, auth, world):
    first = _created(client, auth)
    assert _decide(client, auth, first["id"], "reject").status_code == 200
    second = _check(_created(client, auth, fullName="Another Invented Player"), "submitter")
    assert second["outcome"] == "attention" and "1 of theirs rejected" in second["summary"]


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


def test_approval_creates_a_diaspora_player_whose_seasons_stay_submitted(client, auth, db, world):
    from app.models.consent import Consent
    from app.models.organization import Organization
    from app.models.performance_entry import PerformanceEntry
    from app.models.player import Player

    submission = _created(client, auth)
    approved = _decide(client, auth, submission["id"], "approve")
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "approved" and body["reviewReason"] == "Checked the club's squad page."

    player = db.get(Player, uuid.UUID(body["playerId"]))
    assert (player.tier, player.is_egypt_eligible, player.nationality) == ("diaspora", True, ["EG", "DE"])
    club = db.query(Organization).filter_by(name="FC Invented Nord").one()
    assert (club.country, club.type) == ("DE", "club")
    assert db.query(Consent).filter_by(player_id=player.id, granted=True).count() == 3
    # Not a performance record: nothing in the league analytics reads it.
    assert db.query(PerformanceEntry).filter_by(player_id=player.id).count() == 0

    shown = client.get(f"/players/{player.id}/submitted-seasons", headers=auth("federation")).json()
    (entry,) = shown["submissions"]
    assert entry["clubName"] == "FC Invented Nord" and entry["seasons"][0]["metrics"]["goals"] == 9
    assert "not counted" in shown["note"]


def test_a_second_approval_for_the_same_club_reuses_it(client, auth, db, world):
    from app.models.organization import Organization

    for name in ("Karim Adel Mansour", "Omar Invented Halim"):
        assert _decide(client, auth, _created(client, auth, fullName=name)["id"], "approve").status_code == 200
    assert db.query(Organization).filter_by(name="FC Invented Nord").count() == 1


def test_attach_links_the_submission_to_the_player_on_record(client, auth, db, world):
    from app.models.player import Player

    existing = world["players"]["adult_a"]
    before = db.query(Player).count()
    submission = _created(client, auth)
    assert _decide(client, auth, submission["id"], "attach").status_code == 422  # which player?
    attached = _decide(client, auth, submission["id"], "attach", playerId=str(existing.id)).json()
    assert attached["status"] == "approved" and attached["playerId"] == str(existing.id)
    assert db.query(Player).count() == before


def test_needs_info_goes_back_to_the_submitter_and_an_edit_makes_it_pending(client, auth, world):
    submission = _created(client, auth)
    asked = _decide(client, auth, submission["id"], "needs_info").json()
    assert asked["status"] == "needs_info"
    seen = client.get(f"/submissions/{submission['id']}", headers=auth("scout")).json()
    assert seen["reviewReason"] == "Checked the club's squad page."

    assert client.put(f"/submissions/{submission['id']}", json=_payload(), headers=auth("federation")).status_code == 403
    edited = client.put(f"/submissions/{submission['id']}",
                        json=_payload(sourceUrl="https://example.org/invented-liga/players/karim"),
                        headers=auth("scout"))
    assert edited.status_code == 200 and edited.json()["status"] == "pending"


def test_a_decided_submission_cannot_be_changed_or_decided_again(client, auth, world):
    submission = _created(client, auth)
    assert _decide(client, auth, submission["id"], "reject").status_code == 200
    assert client.put(f"/submissions/{submission['id']}", json=_payload(), headers=auth("scout")).status_code == 422
    assert _decide(client, auth, submission["id"], "approve").status_code == 422


def test_every_step_is_in_the_audit_log(client, auth, db, world):
    from app.models.audit_log import AuditLog

    submission = _created(client, auth)
    _decide(client, auth, submission["id"], "approve")
    actions = {a.action for a in db.query(AuditLog).filter_by(entity_id=uuid.UUID(submission["id"]))}
    assert {"submission.create", "submission.approve"} <= actions
