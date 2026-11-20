"""GET /squad/measuring-plan: whom the coach should measure today (app/services/measuring_plan.py,
ml/decisions/measurement.py). Invented players in the test world."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from tests.conftest import _add_player, withdraw_analytics

TODAY = date.today()


def _height(db, player, days_ago, cm):
    from app.models.measurement import Measurement

    db.add(Measurement(id=uuid.uuid4(), player_id=player.id, measured_at=TODAY - timedelta(days=days_ago),
                       metric="height_cm", value=cm, unit="cm", source="coach_logged", confidence="measured"))


def _get(client, auth, who="coach_a", capacity=None):
    query = "" if capacity is None else f"?capacity={capacity}"
    return client.get(f"/squad/measuring-plan{query}", headers=auth(who))


def test_the_plan_is_the_coachs_own_squad(client, auth, world, db):
    org_a, org_b = world["orgs"]["a"], world["orgs"]["b"]
    mine = _add_player(db, org_a, "Plan Mine", age=13, position="CM", shots=1, n_matches=0)
    theirs = _add_player(db, org_b, "Plan Theirs", age=13, position="CM", shots=1, n_matches=0)
    db.flush()
    body = _get(client, auth, capacity=50).json()
    ids = {row["player"]["id"] for row in body["players"]}
    assert str(mine.id) in ids and str(theirs.id) not in ids
    assert body["capacity"] == 50 and body["plannedFrom"] <= body["squad"]
    assert len(body["players"]) <= 50


def test_capacity_is_respected_and_the_suggestion_is_given(client, auth, world, db):
    org = world["orgs"]["a"]
    for i in range(8):
        _add_player(db, org, f"Plan Squad {i}", age=12 + i % 4, position="CM", shots=1, n_matches=0)
    db.flush()
    body = _get(client, auth, capacity=3).json()
    assert body["capacity"] == 3 and len(body["players"]) == 3
    default = _get(client, auth).json()
    assert default["capacity"] == default["suggested"] > 0
    # About every three months for everyone: a 28-day session measures about a third.
    assert default["suggested"] >= default["plannedFrom"] * 28 / 91


def test_an_unmeasured_young_player_comes_first_and_says_why(client, auth, world, db):
    org = world["orgs"]["a"]
    young = _add_player(db, org, "Plan Young", age=13, position="CM", shots=1, n_matches=0)
    adult = _add_player(db, org, "Plan Adult", age=25, position="CM", shots=1, n_matches=0)
    for days in (30, 120, 210, 300):
        _height(db, adult, days, 180.0)
    db.flush()
    body = _get(client, auth, capacity=1).json()
    row = body["players"][0]
    assert row["player"]["id"] == str(young.id)
    assert row["readingsLastYear"] == 0 and row["daysSinceLast"] is None
    assert any("before the late-bloomer check" in r for r in row["reasons"])
    assert "never measured" in row["reasons"]


def test_players_without_analytics_consent_are_counted_not_planned(client, auth, world, db):
    org = world["orgs"]["a"]
    private = _add_player(db, org, "Plan Private", age=13, position="CM", shots=1, n_matches=0)
    withdraw_analytics(db, private)
    db.flush()
    body = _get(client, auth, capacity=100).json()
    assert str(private.id) not in {row["player"]["id"] for row in body["players"]}
    assert body["withoutConsent"] >= 1


def test_only_a_coach_gets_a_plan(client, auth, world):
    for who in ("scout", "federation", "admin", "player_self"):
        assert _get(client, auth, who).status_code == 403
    assert _get(client, auth, "coach_orphan").json()["players"] == []


def test_capacity_out_of_range_is_refused(client, auth, world):
    assert _get(client, auth, capacity=-1).status_code == 422
    assert _get(client, auth, capacity=10_000).status_code == 422
