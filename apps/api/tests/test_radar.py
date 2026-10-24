"""GET /players/{id}/radar (app/services/radar.py).

The radar's rules are the profile's: no percentile from fewer than cohort.MIN_COHORT players,
the population always named, only players with analytics consent compared, and a goalkeeper
shown only on statistics that mean something for one.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.cohort import MIN_COHORT
from tests.conftest import _add_player

TODAY = date.today()


def _radar(client, auth, player, who="federation"):
    return client.get(f"/players/{player.id}/radar", headers=auth(who))


def _axis(body, key):
    return next(a for a in body["axes"] if a["key"] == key)


def test_a_player_is_placed_among_comparable_players_and_the_population_is_named(
    client, auth, forwards
):
    best, worst = forwards[-1], forwards[0]
    top = _radar(client, auth, best).json()
    bottom = _radar(client, auth, worst).json()
    assert "forwards, boys aged 15" in top["population"]
    assert _axis(top, "shots")["percentile"] > 90
    assert _axis(bottom, "shots")["percentile"] < 10
    assert _axis(top, "shots")["value"] == pytest.approx(len(forwards), abs=0.01)


def test_an_axis_where_everyone_is_equal_has_no_percentile(client, auth, forwards):
    """Every forward here has 2 tackles a match. A percentile of 50 would look like a finding."""
    assert _axis(_radar(client, auth, forwards[0]).json(), "tackles")["percentile"] is None


def test_too_few_comparable_players_gives_no_percentile(client, auth, world, db, only):
    org = world["orgs"]["a"]
    few = [
        _add_player(db, org, f"Radar Winger {i}", age=10.2, position="LW", shots=i)
        for i in range(1, MIN_COHORT - 2)
    ]
    db.flush()
    only(few)
    body = _radar(client, auth, few[0]).json()
    assert all(a["percentile"] is None for a in body["axes"])
    assert f"fewer than {MIN_COHORT}" in body["note"]


def test_without_analytics_consent_there_is_no_radar_and_no_place_in_others(
    client, auth, world, db, forwards
):
    from tests.conftest import withdraw_analytics

    withdrawn = forwards[-1]
    withdraw_analytics(db, withdrawn)
    db.flush()
    own = _radar(client, auth, withdrawn).json()
    assert own["axes"] == [] and "consent" in own["note"].lower()
    other = _radar(client, auth, forwards[0]).json()
    assert f": {len(forwards) - 1} with enough" in other["population"]


def test_a_goalkeeper_is_shown_on_passing_and_distance_only(
    client, auth, world, db, forwards, only
):
    org = world["orgs"]["a"]
    keepers = [
        _add_player(db, org, f"Radar Keeper {i}", age=15.4, position="GK", shots=0)
        for i in range(MIN_COHORT)
    ]
    db.flush()
    only(keepers)
    body = _radar(client, auth, keepers[0]).json()
    assert {a["key"] for a in body["axes"]} == {"passes_attempted", "pass_completion", "distance_km"}
    assert "no goalkeeping statistics" in body["note"]


def test_a_player_the_caller_may_not_see_is_404(client, auth, world):
    assert _radar(client, auth, world["players"]["minor_no_a"], who="scout").status_code == 404
