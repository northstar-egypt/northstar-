"""GET /players/{id}/weak-points (app/services/weak_points.py).

What is pinned: weak points come only from statistics that have a percentile and matter for the
position, each has drills, progress is the player's own numbers, and the same consent and
access rules as the radar hold.
"""

from __future__ import annotations


def _get(client, auth, who, player):
    return client.get(f"/players/{player.id}/weak-points", headers=auth(who))


def test_a_forward_who_rarely_shoots_gets_shots_as_a_weak_point(client, auth, forwards):
    body = _get(client, auth, "federation", forwards[0]).json()
    keys = [w["key"] for w in body["items"]]
    assert "shots" in keys, body
    for w in body["items"]:
        assert w["percentile"] < 40 and w["drills"]
        assert w["key"] != "tackles"  # not a forward's weakness
    assert body["progress"] and "shots" in body["progress"][-1]["values"]


def test_without_analytics_consent_nothing_is_judged(client, auth, db, forwards):
    from tests.conftest import withdraw_analytics

    withdraw_analytics(db, forwards[0])
    body = _get(client, auth, "federation", forwards[0]).json()
    assert body["items"] == [] and "consent" in body["note"].lower()


def test_a_player_the_caller_may_not_see_is_404(client, auth, world):
    assert _get(client, auth, "scout", world["players"]["minor_no_a"]).status_code == 404
