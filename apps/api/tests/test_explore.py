"""GET /explore/scatter (app/services/explore.py).

The explorer's rules are the radar's: only players with analytics consent, median lines only
from cohort.MIN_COHORT players or more, and the group always named. Plus its own: a point is
drawn only for a player the caller may open, and the others are counted, never identified.
"""

from __future__ import annotations

from sqlalchemy import select

from app.services.cohort import MIN_COHORT
from tests.test_radar import _add_player, forwards, only  # noqa: F401  (fixtures)


def _scatter(client, auth, who="federation", **params):
    return client.get("/explore/scatter", params=params, headers=auth(who))


def test_every_comparable_player_is_a_point_and_the_group_is_named(client, auth, forwards):
    body = _scatter(client, auth, group="forward", ageFrom=15, ageTo=15).json()
    assert body["x"] == "shots" and body["y"] == "goals"
    assert body["total"] == len(forwards)
    assert len(body["points"]) == len(forwards)
    assert "forwards, men and boys aged 15" in body["population"]
    shots = sorted(p["x"] for p in body["points"])
    assert shots[0] == 1 and shots[-1] == len(forwards)
    assert 5 <= body["medians"]["x"] <= 6


def test_a_small_group_gets_no_median_lines(client, auth, world, db, only):
    org = world["orgs"]["a"]
    few = [
        _add_player(db, org, f"Scatter Winger {i}", age=10.2, position="LW", shots=i)
        for i in range(1, MIN_COHORT - 2)
    ]
    db.flush()
    only(few)
    body = _scatter(client, auth, group="forward").json()
    assert body["total"] == len(few)
    assert body["medians"] is None
    assert f"Fewer than {MIN_COHORT}" in body["note"]


def test_a_scout_sees_no_point_for_a_minor_hidden_from_scouts_but_they_are_counted(
    client, auth, db, forwards
):
    from app.models.consent import Consent
    from app.models.enums import ConsentPurpose

    hidden = forwards[0]
    row = db.execute(
        select(Consent)
        .where(Consent.player_id == hidden.id)
        .where(Consent.purpose == ConsentPurpose.SCOUTING_VISIBILITY.value)
    ).scalar_one()
    row.granted = False
    db.flush()

    body = _scatter(client, auth, who="scout", group="forward").json()
    ids = {p["playerId"] for p in body["points"]}
    assert str(hidden.id) not in ids
    assert len(ids) == len(forwards) - 1
    assert body["total"] == len(forwards)
    assert "not drawn" in body["note"]
    assert f"'{hidden.full_name}'" not in str(body)


def test_a_coach_sees_only_their_own_squad_as_points(client, auth, forwards):
    """The forwards are at academy A. Coach B gets the group's shape and no names."""
    body = _scatter(client, auth, who="coach_b", group="forward").json()
    assert body["points"] == []
    assert body["total"] == len(forwards)
    own = _scatter(client, auth, who="coach_a", group="forward").json()
    assert len(own["points"]) == len(forwards)


def test_without_analytics_consent_a_player_is_not_in_the_group(client, auth, db, forwards):
    from tests.conftest import withdraw_analytics

    withdraw_analytics(db, forwards[-1])
    db.flush()
    body = _scatter(client, auth, group="forward").json()
    assert body["total"] == len(forwards) - 1
    assert str(forwards[-1].id) not in {p["playerId"] for p in body["points"]}


def test_a_focus_player_sets_the_group_and_is_marked(client, auth, forwards):
    body = _scatter(client, auth, focus=str(forwards[3].id)).json()
    assert body["group"] == "forward" and body["sport"] == "football"
    assert body["focus"] == str(forwards[3].id)


def test_a_focus_the_caller_may_not_open_is_ignored_like_an_unknown_id(client, auth, world):
    hidden = _scatter(client, auth, who="scout", focus=str(world["players"]["minor_no_a"].id))
    assert hidden.status_code == 200 and hidden.json()["focus"] is None


def test_a_goalkeeper_plot_offers_no_scoring_statistics(client, auth):
    body = _scatter(client, auth, group="goalkeeper").json()
    assert {s["key"] for s in body["stats"]} == {"passes_attempted", "pass_completion", "distance_km"}
    assert _scatter(client, auth, group="goalkeeper", x="goals").status_code == 400


def test_bad_filters_are_400_with_a_reason(client, auth):
    assert _scatter(client, auth, sport="cricket").status_code == 400
    assert _scatter(client, auth, sport="football", gender="female").status_code == 400
    assert _scatter(client, auth, ageFrom=16, ageTo=12).status_code == 400
    table_tennis = _scatter(client, auth, sport="table_tennis", gender="female").json()
    assert table_tennis["groups"] == [] and table_tennis["gender"] == "female"
