"""GET /explore/scatter (app/services/explore.py).

The explorer's rules are the radar's: only players with analytics consent, median lines only
from cohort.MIN_COHORT players or more, and the group always named. Plus its own: a point is
drawn only for a player the caller may open, and the others are counted, never identified.
"""

from __future__ import annotations

from sqlalchemy import select

from app.services.cohort import MIN_COHORT
from tests.conftest import _add_player


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


# --------------------------------------------------------------------------- leaders


def _leaders(client, auth, who="federation", **params):
    return client.get("/explore/leaders", params=params, headers=auth(who))


def _board(body, key):
    return next(b for b in body["boards"] if b["key"] == key)


def test_the_leaders_of_a_group_are_its_best_with_a_percentile_among_all_of_it(
    client, auth, forwards
):
    body = _leaders(client, auth, group="forward").json()
    shots = _board(body, "shots")
    assert [row["playerId"] for row in shots["leaders"]] == [
        str(p.id) for p in reversed(forwards[-5:])
    ]
    assert shots["leaders"][0]["percentile"] > 90
    assert 5 <= shots["median"] <= 6
    assert shots["comparedWith"] == len(forwards)
    assert "forwards, men and boys of every age" in body["population"]


def test_a_statistic_where_everyone_is_equal_has_no_leaders(client, auth, forwards):
    """Every forward here has 2 tackles a match. Any order among them would be invented."""
    tackles = _board(_leaders(client, auth, group="forward").json(), "tackles")
    assert tackles["median"] is None and tackles["leaders"] == []
    assert "no leaders" in _leaders(client, auth, group="forward").json()["note"]


def test_a_coach_gets_the_groups_shape_but_no_names_from_other_clubs(client, auth, forwards):
    body = _leaders(client, auth, who="coach_b", group="forward").json()
    assert body["total"] == len(forwards) and body["shown"] == 0
    assert all(b["leaders"] == [] for b in body["boards"])
    assert _board(body, "shots")["median"] is not None


def test_a_scout_never_sees_a_minor_hidden_from_scouts_among_the_leaders(
    client, auth, db, forwards
):
    from app.models.consent import Consent
    from app.models.enums import ConsentPurpose

    best = forwards[-1]
    row = db.execute(
        select(Consent)
        .where(Consent.player_id == best.id)
        .where(Consent.purpose == ConsentPurpose.SCOUTING_VISIBILITY.value)
    ).scalar_one()
    row.granted = False
    db.flush()

    body = _leaders(client, auth, who="scout", group="forward").json()
    assert str(best.id) not in str(body)
    shots = _board(body, "shots")
    # The next best leads, and is still placed among everyone, the hidden player included.
    assert shots["leaders"][0]["playerId"] == str(forwards[-2].id)
    assert shots["comparedWith"] == len(forwards)


def test_each_board_says_where_the_focus_player_stands(client, auth, forwards):
    worst = forwards[0]
    body = _leaders(client, auth, focus=str(worst.id)).json()
    assert body["group"] == "forward" and body["focus"] == str(worst.id)
    shots = _board(body, "shots")
    assert shots["focus"]["rank"] == len(forwards)
    assert shots["focus"]["percentile"] < 10


# --------------------------------------------------------------------------- own age


def test_a_focus_player_opens_on_their_own_age(client, auth, world, db, forwards, only):
    """Ten 15-year-old forwards are enough on their own, so a 19-year-old is left out."""
    adult = _add_player(db, world["orgs"]["a"], "Scatter Adult", age=19.5, position="ST", shots=20)
    db.flush()
    only([adult])
    body = _scatter(client, auth, focus=str(forwards[0].id)).json()
    assert (body["ageFrom"], body["ageTo"]) == (15, 15)
    assert "aged 15:" in body["population"]
    assert str(adult.id) not in {p["playerId"] for p in body["points"]}
    leaders = _leaders(client, auth, focus=str(forwards[0].id)).json()
    assert (leaders["ageFrom"], leaders["ageTo"]) == (15, 15)


def test_too_few_of_their_own_age_widens_a_year_either_side(client, auth, world, db, only):
    org = world["orgs"]["a"]
    at_12 = [_add_player(db, org, f"Scatter Twelve {i}", age=12.5, position="CM", shots=i) for i in range(3)]
    at_13 = [_add_player(db, org, f"Scatter Thirteen {i}", age=13.5, position="CM", shots=i) for i in range(3)]
    at_11 = [_add_player(db, org, f"Scatter Eleven {i}", age=11.5, position="CM", shots=i) for i in range(3)]
    db.flush()
    only(at_11, at_12, at_13)
    body = _scatter(client, auth, focus=str(at_12[0].id)).json()
    assert (body["ageFrom"], body["ageTo"]) == (11, 13)
    assert body["total"] == 9


def test_an_adult_is_compared_with_adults(client, auth, world, db, forwards, only):
    adults = [
        _add_player(db, world["orgs"]["a"], f"Scatter Senior {i}", age=24 + i, position="ST", shots=i)
        for i in range(3)
    ]
    db.flush()
    only(adults)
    body = _scatter(client, auth, focus=str(adults[0].id)).json()
    assert (body["ageFrom"], body["ageTo"]) == (18, None)
    assert body["total"] == len(adults)


def test_own_age_off_keeps_every_age(client, auth, world, db, forwards, only):
    adult = _add_player(db, world["orgs"]["a"], "Scatter Adult", age=19.5, position="ST", shots=20)
    db.flush()
    only([adult])
    body = _scatter(client, auth, focus=str(forwards[0].id), ownAge="false").json()
    assert body["ageFrom"] is None and body["ageTo"] is None
    assert body["total"] == len(forwards) + 1
