"""Access control tests.

This file is the start of the graded RBAC deliverable ("every RBAC test must pass"). Every
rule in `app/services/access.py` should have a case here, and each one is written so that it
fails if the rule is removed rather than merely passing when it is present.

Two behaviours are load-bearing and get several tests each:

  A player the caller may not see returns **404, not 403**. A distinguishable status code
  tells an unauthorised caller that the player exists, which for a child without scouting
  consent is precisely the disclosure the consent rule is there to prevent.

  A withheld search result carries **no identifying fields**. The locked card says a record
  exists; it must not leak the name or the date of birth of the child behind it.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Authentication stand-in
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/me", "/players", "/oversight"],
)
def test_no_identity_is_rejected(client, world, path):
    assert client.get(path).status_code == 401


def test_unknown_user_is_rejected(client, world):
    response = client.get("/players", headers={"X-NorthStar-User": "nobody@test.invalid"})
    assert response.status_code == 401


def test_inactive_user_is_rejected(client, auth):
    """A deactivated account is not a valid caller. Otherwise disabling someone does nothing."""
    assert client.get("/players", headers=auth("inactive")).status_code == 401


def test_health_needs_no_identity(client):
    """Health checks are unauthenticated on purpose: the container probe has no credentials."""
    assert client.get("/health").status_code == 200


def test_identity_header_is_refused_outside_development(client, auth, monkeypatch):
    """The development stand-in must not work anywhere else, including by accident.

    This is the test that stops the header becoming a back door if the module is ever
    deployed with the environment set to anything other than development.
    """
    from app.config import Settings, get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    try:
        assert Settings().environment == "production"
        response = client.get("/players", headers=auth("admin"))
        assert response.status_code == 401
        assert "not implemented" in response.json()["detail"].lower()
    finally:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Squad scoping
# ---------------------------------------------------------------------------


def test_coach_sees_only_their_own_organization(client, auth, world):
    rows = client.get("/players", headers=auth("coach_a")).json()
    names = {row["player"]["fullName"] for row in rows}
    assert {"Adult A", "Minor Consented A", "Minor Blocked A"} <= names
    assert "Adult B" not in names
    assert "Minor Blocked B" not in names


def test_coach_with_no_organization_sees_nobody(client, auth, world):
    """Fails closed. A broken account shows an empty squad rather than the whole country."""
    assert client.get("/players", headers=auth("coach_orphan")).json() == []


def test_player_sees_only_themselves(client, auth, world):
    rows = client.get("/players", headers=auth("player_self")).json()
    assert len(rows) == 1
    assert rows[0]["player"]["fullName"] == "Adult A"


def test_federation_and_admin_see_across_organizations(client, auth, world):
    for who in ("federation", "admin"):
        names = {row["player"]["fullName"] for row in client.get("/players", headers=auth(who)).json()}
        assert {"Adult A", "Adult B"} <= names, who


# ---------------------------------------------------------------------------
# Profile access and the consent gate
# ---------------------------------------------------------------------------


def test_coach_cannot_open_a_player_from_another_organization(client, auth, world):
    player_id = world["players"]["adult_b"].id
    response = client.get(f"/players/{player_id}/profile", headers=auth("coach_a"))
    # 404 rather than 403: coach A should not learn that this player exists.
    assert response.status_code == 404


def test_scout_cannot_open_a_minor_without_scouting_consent(client, auth, world):
    player_id = world["players"]["minor_no_a"].id
    response = client.get(f"/players/{player_id}/profile", headers=auth("scout"))
    assert response.status_code == 404


def test_scout_can_open_a_minor_with_scouting_consent(client, auth, world):
    player_id = world["players"]["minor_ok_a"].id
    assert client.get(f"/players/{player_id}/profile", headers=auth("scout")).status_code == 200


def test_scout_can_open_an_adult(client, auth, world):
    """Consent gates minors. An adult is not withheld for lack of a guardian's signature."""
    player_id = world["players"]["adult_a"].id
    assert client.get(f"/players/{player_id}/profile", headers=auth("scout")).status_code == 200


def test_the_players_own_coach_still_sees_them_without_scouting_consent(client, auth, world):
    """Consent for scouting visibility is not consent to exist.

    If this rule inverted, declining to be shown to scouts would also hide a child from the
    coach who measures them, which would make declining unusable.
    """
    player_id = world["players"]["minor_no_a"].id
    assert client.get(f"/players/{player_id}/profile", headers=auth("coach_a")).status_code == 200


def test_player_cannot_open_someone_elses_profile(client, auth, world):
    player_id = world["players"]["minor_ok_a"].id
    assert (
        client.get(f"/players/{player_id}/profile", headers=auth("player_self")).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# Permissions object
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "who,expected",
    [
        ("coach_a", {"canEdit": True, "canLog": True, "canSeeFlags": True}),
        ("federation", {"canEdit": False, "canLog": False, "canSeeFlags": True}),
        ("scout", {"canEdit": False, "canLog": False, "canSeeFlags": True}),
        ("admin", {"canEdit": True, "canLog": True, "canSeeFlags": True}),
    ],
)
def test_permissions_are_decided_by_the_api(client, auth, world, who, expected):
    player_id = world["players"]["adult_a"].id
    body = client.get(f"/players/{player_id}/profile", headers=auth(who)).json()
    assert body["permissions"] == expected


def test_a_player_does_not_see_flags_about_themselves(client, auth, world):
    """An open fairness question, decided this way on purpose.

    There is no route for a player to dispute a flag, so showing one would tell a child a
    model has doubts about them with nothing they can do. Recorded in the player profile
    wireframe and enforced here so the decision is visible rather than implicit.
    """
    player_id = world["players"]["adult_a"].id
    body = client.get(f"/players/{player_id}/profile", headers=auth("player_self")).json()
    assert body["permissions"]["canSeeFlags"] is False
    assert body["permissions"]["canEdit"] is True


# ---------------------------------------------------------------------------
# Search: withheld results
# ---------------------------------------------------------------------------


def test_withheld_results_carry_no_identifying_fields(client, auth, world):
    body = client.post("/search", json={"query": ""}, headers=auth("scout")).json()
    withheld = [row for row in body["results"] if row["withheld"]]
    assert withheld, "expected at least one minor without scouting consent"
    for row in withheld:
        assert row["player"]["fullName"] == "Withheld"
        assert row["player"]["dateOfBirth"] is None
        assert row["player"]["nationality"] == []
        assert row["ageLabel"] == ""
        assert row["heightCm"] is None
        assert row["trend"] == []
        assert row["withheldReason"]


def test_a_blocked_minor_is_reported_not_hidden(client, auth, world):
    """The locked card, which is what the wireframe drew.

    Whether this is right is still open. If the team chooses to omit them instead, this test
    is the one to invert, and the change is a filter in the search router.
    """
    blocked_id = str(world["players"]["minor_no_a"].id)
    body = client.post("/search", json={"query": ""}, headers=auth("scout")).json()
    ids = {row["player"]["id"]: row for row in body["results"]}
    assert blocked_id in ids
    assert ids[blocked_id]["withheld"] is True


def test_coach_search_does_not_reach_other_organizations(client, auth, world):
    body = client.post("/search", json={"query": ""}, headers=auth("coach_a")).json()
    names = {row["player"]["fullName"] for row in body["results"]}
    assert "Adult B" not in names


# ---------------------------------------------------------------------------
# Oversight
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("who,expected", [("federation", 200), ("admin", 200), ("scout", 403), ("coach_a", 403)])
def test_oversight_is_limited_to_federation_and_admin(client, auth, who, expected):
    assert client.get("/oversight", headers=auth(who)).status_code == expected


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def test_comparison_drops_players_the_caller_may_not_see(client, auth, world):
    """Asking to compare against a player you cannot see must not reveal them.

    Coach A compares one of their own with one of academy B's. The out-of-scope player is
    dropped, which leaves fewer than two, which is a 404.
    """
    a = world["players"]["adult_a"].id
    b = world["players"]["adult_b"].id
    response = client.get(f"/compare?players={a},{b}", headers=auth("coach_a"))
    assert response.status_code == 404


def test_comparison_needs_at_least_two_players(client, auth, world):
    a = world["players"]["adult_a"].id
    assert client.get(f"/compare?players={a}", headers=auth("coach_a")).status_code == 400


def test_comparison_rejects_more_than_four(client, auth, world):
    ids = ",".join(str(player.id) for player in world["players"].values())
    assert client.get(f"/compare?players={ids}", headers=auth("admin")).status_code == 400


# ---------------------------------------------------------------------------
# Development helpers
# ---------------------------------------------------------------------------


def test_dev_identities_lists_one_account_per_role(client, world):
    """The role switcher needs real accounts to act as. See `app/routers/dev.py`."""
    body = client.get("/dev/identities").json()
    roles = {row["role"] for row in body}
    assert {"coach", "scout", "federation", "admin"} <= roles
    for row in body:
        assert row["email"]


def test_dev_identities_is_refused_outside_development(client, monkeypatch):
    """Gated by the same check as the identity header, so the two cannot drift apart."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    try:
        assert client.get("/dev/identities").status_code == 404
    finally:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        get_settings.cache_clear()
