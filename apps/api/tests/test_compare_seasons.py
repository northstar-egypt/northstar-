"""GET /compare, the league-seasons section: professionals side by side on their basic seasons
(app/services/pro_compare.py). Invented players and invented competitions; the event names keep
them apart from anything else in the database."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from tests.conftest import _add_player, withdraw_analytics

SCHEMA = "football.season_basic.v1"


def _season(db, player, org, competition, start_year, *, group="forward", minutes=2700, goals=10,
            assists=5, pens=0, apps=30, yellow=2, red=0):
    """One basic season, as the FootyStats load writes it."""
    from app.models.performance_entry import PerformanceEntry

    label = f"{start_year}/{str(start_year + 1)[-2:]}"
    db.add(PerformanceEntry(
        id=uuid.uuid4(), player_id=player.id, sport="football", period_type="season_aggregate",
        period_start=date(start_year, 8, 1), period_end=date(start_year + 1, 5, 30), organization_id=org.id,
        event=f"{competition} {label}", schema_ref=SCHEMA, source="footystats", is_validated=True,
        metrics={"position_group": group, "appearances": apps, "minutes_played": minutes, "goals": goals,
                 "assists": assists, "penalty_goals": pens, "yellow_cards": yellow, "red_cards": red},
    ))


def _pro(db, org, name, age=26):
    return _add_player(db, org, name, age=age, position=None, shots=1, n_matches=0)


def _compare(client, auth, *players, who="scout"):
    ids = ",".join(str(p.id) for p in players)
    response = client.get(f"/compare?players={ids}", headers=auth(who))
    assert response.status_code == 200, response.text
    return response.json()


def _row(section, label):
    return next(m for m in section["metrics"] if m["label"] == label)


def test_two_professionals_are_compared_on_the_season_they_share(client, auth, world, db):
    org = world["orgs"]["a"]
    a, b = _pro(db, org, "Seasons Alpha"), _pro(db, org, "Seasons Beta")
    _season(db, a, org, "Seasons League", 2030, minutes=2700, goals=15, pens=3, assists=6)
    _season(db, b, org, "Seasons League", 2030, minutes=1800, goals=4, assists=8)
    db.flush()

    section = _compare(client, auth, a, b)["seasons"]
    assert section["basis"] == "same season" and section["caveat"] is None
    assert [(p["competition"], p["season"]) for p in section["players"]] == [("Seasons League", "2030/31")] * 2
    assert _row(section, "Goals")["values"] == [15, 4]
    # Non-penalty: 12 goals in 30 matches' worth of minutes, and 4 in 20.
    assert _row(section, "Non-penalty goals per 90")["values"] == pytest.approx([12 / 30, 4 / 20])
    assert _row(section, "Assists per 90")["values"] == pytest.approx([6 / 30, 8 / 20])
    assert _row(section, "Yellow cards")["higherIsBetter"] is False


def test_the_most_recent_season_they_share_is_used(client, auth, world, db):
    org = world["orgs"]["a"]
    a, b = _pro(db, org, "Seasons Gamma"), _pro(db, org, "Seasons Delta")
    for year, goals in ((2028, 1), (2029, 2)):
        _season(db, a, org, "Seasons Shared", year, goals=goals)
        _season(db, b, org, "Seasons Shared", year, goals=goals + 10)
    _season(db, a, org, "Seasons Shared", 2030, goals=3)  # only A has the latest
    db.flush()

    section = _compare(client, auth, a, b)["seasons"]
    assert section["basis"] == "same season"
    assert {p["season"] for p in section["players"]} == {"2029/30"}
    assert _row(section, "Goals")["values"] == [2, 12]


def test_with_no_season_in_common_each_is_shown_on_their_latest_and_it_says_so(client, auth, world, db):
    org = world["orgs"]["a"]
    a, b = _pro(db, org, "Seasons Epsilon"), _pro(db, org, "Seasons Zeta")
    _season(db, a, org, "Seasons North", 2029)
    _season(db, a, org, "Seasons North", 2030)
    _season(db, b, org, "Seasons South", 2030)
    db.flush()

    section = _compare(client, auth, a, b)["seasons"]
    assert section["basis"] == "most recent season each"
    assert "no season in common" in section["caveat"]
    assert [(p["competition"], p["season"]) for p in section["players"]] == [
        ("Seasons North", "2030/31"), ("Seasons South", "2030/31")]


def test_rates_are_left_out_below_450_minutes_and_the_row_says_why(client, auth, world, db):
    org = world["orgs"]["a"]
    a, b = _pro(db, org, "Seasons Eta"), _pro(db, org, "Seasons Theta")
    _season(db, a, org, "Seasons Short", 2030, minutes=449, goals=3)
    _season(db, b, org, "Seasons Short", 2030, minutes=450, goals=3)
    db.flush()

    per_90 = _row(_compare(client, auth, a, b)["seasons"], "Non-penalty goals per 90")
    assert per_90["values"][0] is None and per_90["values"][1] == pytest.approx(3 / 5)
    assert "450 minutes" in per_90["note"]


def test_different_position_groups_are_warned_about(client, auth, world, db):
    org = world["orgs"]["a"]
    a, b = _pro(db, org, "Seasons Iota"), _pro(db, org, "Seasons Kappa")
    _season(db, a, org, "Seasons Groups", 2030, group="forward")
    _season(db, b, org, "Seasons Groups", 2030, group="defender")
    db.flush()

    section = _compare(client, auth, a, b)["seasons"]
    assert "defender, forward" in section["caveat"]
    assert [p["positionGroup"] for p in section["players"]] == ["forward", "defender"]


def test_a_move_within_the_league_is_one_season_with_both_clubs(client, auth, world, db):
    from app.models.organization import Organization

    org = world["orgs"]["a"]
    other = Organization(id=uuid.uuid4(), name="Seasons Second Club", type="club", country="EG")
    db.add(other)
    db.flush()
    a, b = _pro(db, org, "Seasons Lambda"), _pro(db, org, "Seasons Mu")
    _season(db, a, org, "Seasons Moves", 2030, minutes=900, goals=2, apps=10, group="midfielder")
    _season(db, a, other, "Seasons Moves", 2030, minutes=1800, goals=4, apps=20, group="forward")
    _season(db, b, org, "Seasons Moves", 2030)
    db.flush()

    section = _compare(client, auth, a, b)["seasons"]
    column = section["players"][0]
    assert sorted(column["clubs"]) == sorted([org.name, "Seasons Second Club"])
    # The group the player spent most minutes in.
    assert column["positionGroup"] == "forward"
    assert _row(section, "Goals")["values"][0] == 6
    assert _row(section, "Minutes")["values"][0] == 2700
    assert _row(section, "Appearances")["values"][0] == 30


def test_youth_players_get_no_league_seasons_section(client, auth, world):
    a = world["players"]["minor_ok_a"].id
    b = world["players"]["minor_no_a"].id
    body = client.get(f"/compare?players={a},{b}", headers=auth("coach_a")).json()
    assert body["seasons"] is None
    assert any(m["label"] == "Height" for m in body["metrics"])  # the youth comparison is unchanged


def test_a_player_with_no_seasons_beside_one_with_seasons_is_told_so(client, auth, world, db):
    org = world["orgs"]["a"]
    a, b = _pro(db, org, "Seasons Nu"), _pro(db, org, "Seasons Xi")
    _season(db, a, org, "Seasons Lonely", 2030)
    db.flush()

    section = _compare(client, auth, a, b)["seasons"]
    assert section["players"][1]["note"] == "No league seasons on record."
    assert _row(section, "Goals")["values"][1] is None


def _league(db, org, competition, n=30):
    """`n` forwards with a spread of scoring rates, so the estimates have peers to fit on."""
    for i in range(n):
        peer = _pro(db, org, f"Seasons Peer {competition} {i}", age=25)
        _season(db, peer, org, competition, 2030, minutes=900 + 60 * i, goals=i % 12, assists=i % 7)


def test_the_estimates_come_with_their_range_and_are_not_ranked_when_ranges_overlap(client, auth, world, db):
    org = world["orgs"]["a"]
    _league(db, org, "Seasons Estimates")
    star, cold = _pro(db, org, "Seasons Star"), _pro(db, org, "Seasons Cold")
    twin = _pro(db, org, "Seasons Twin")
    _season(db, star, org, "Seasons Estimates", 2030, minutes=3000, goals=30, assists=2)
    _season(db, cold, org, "Seasons Estimates", 2030, minutes=3000, goals=0, assists=2)
    _season(db, twin, org, "Seasons Estimates", 2030, minutes=3000, goals=29, assists=2)
    db.flush()

    apart = _row(_compare(client, auth, star, cold)["seasons"], "Non-penalty goals per 90, estimated")
    assert apart["values"][0] > apart["values"][1]
    for value, low, high in zip(apart["values"], apart["lows"], apart["highs"]):
        assert low <= value <= high
    assert apart["percentiles"][0] > apart["percentiles"][1]
    assert apart["indistinguishable"] is None

    close = _row(_compare(client, auth, star, twin)["seasons"], "Non-penalty goals per 90, estimated")
    assert close["indistinguishable"] is True and "not told apart" in close["note"]


def test_without_analytics_consent_there_is_no_estimate_but_the_counts_stay(client, auth, world, db):
    org = world["orgs"]["a"]
    _league(db, org, "Seasons Consent")
    a, b = _pro(db, org, "Seasons Omicron"), _pro(db, org, "Seasons Pi")
    _season(db, a, org, "Seasons Consent", 2030, goals=12)
    _season(db, b, org, "Seasons Consent", 2030, goals=7)
    withdraw_analytics(db, b)
    db.flush()

    section = _compare(client, auth, a, b)["seasons"]
    assert _row(section, "Goals")["values"] == [12, 7]
    estimated = _row(section, "Non-penalty goals per 90, estimated")
    assert estimated["values"][0] is not None and estimated["values"][1] is None
    assert "Seasons Pi" in estimated["note"] and "consent" in estimated["note"]
