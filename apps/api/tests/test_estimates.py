"""GET /players/{id}/estimates: a professional's rates against league peers, shrunk by how much
has been seen (app/services/estimates.py, ml/estimates). Invented players and an invented
league; the event names keep them apart from anything else in the database."""

from __future__ import annotations

import uuid
from datetime import date

from tests.conftest import _add_player, withdraw_analytics

SCHEMA = "football.season_basic.v1"


def _season(db, player, org, event, *, group, minutes, goals, assists, pens=0):
    from app.models.performance_entry import PerformanceEntry

    db.add(PerformanceEntry(
        id=uuid.uuid4(), player_id=player.id, sport="football", period_type="season_aggregate",
        period_start=date(2030, 8, 1), period_end=date(2031, 5, 30), organization_id=org.id,
        event=event, schema_ref=SCHEMA, source="footystats", is_validated=True,
        metrics={"position_group": group, "appearances": 30, "minutes_played": minutes, "goals": goals,
                 "assists": assists, "penalty_goals": pens, "yellow_cards": 2, "red_cards": 0},
    ))


def _league(db, org, event, n=30, group="forward"):
    """`n` peers with a spread of scoring rates."""
    peers = []
    for i in range(n):
        p = _add_player(db, org, f"Invented Peer {event} {i}", age=25, position=None, shots=1, n_matches=0)
        _season(db, p, org, event, group=group, minutes=900 + 60 * i, goals=i % 12, assists=i % 7)
        peers.append(p)
    return peers


def _get(client, auth, player, who="scout"):
    return client.get(f"/players/{player.id}/estimates", headers=auth(who))


def test_a_scorer_is_estimated_against_their_peers(client, auth, world, db):
    org = world["orgs"]["a"]
    event = "Invented League 2030/31"
    _league(db, org, event)
    star = _add_player(db, org, "Invented Star", age=24, position=None, shots=1, n_matches=0)
    _season(db, star, org, event, group="forward", minutes=3000, goals=25, assists=10, pens=5)
    db.flush()

    body = _get(client, auth, star).json()
    assert body["note"] is None
    season = body["seasons"][0]
    assert (season["competition"], season["season"], season["group"]) == ("Invented League", "2030/31", "forward")
    goals = next(m for m in season["measures"] if m["key"] == "np_goals")
    # Non-penalty goals: 25 minus 5 penalties.
    assert goals["count"] == 20 and goals["raw"] == 20 / (3000 / 90)
    # Pulled towards the peers, never past them, and inside its own interval.
    assert goals["peerRate"] < goals["estimate"] < goals["raw"]
    assert goals["low"] <= goals["estimate"] <= goals["high"]
    assert 0 < goals["weight"] < 1
    assert goals["percentileLow"] <= goals["percentile"] <= goals["percentileHigh"]
    assert goals["percentile"] >= 90
    # Ranked among the others: the player is not their own peer.
    assert goals["peers"] == 30


def test_a_short_season_is_shown_with_a_wide_range_not_hidden(client, auth, world, db):
    org = world["orgs"]["a"]
    event = "Invented League B 2030/31"
    _league(db, org, event)
    cameo = _add_player(db, org, "Invented Cameo", age=19, position=None, shots=1, n_matches=0)
    _season(db, cameo, org, event, group="forward", minutes=180, goals=2, assists=0)
    regular = _add_player(db, org, "Invented Regular", age=27, position=None, shots=1, n_matches=0)
    _season(db, regular, org, event, group="forward", minutes=3000, goals=33, assists=0)
    db.flush()

    short = next(m for m in _get(client, auth, cameo).json()["seasons"][0]["measures"] if m["key"] == "np_goals")
    full = next(m for m in _get(client, auth, regular).json()["seasons"][0]["measures"] if m["key"] == "np_goals")
    # The same raw rate (1.0 and 0.99 per 90), but the cameo is mostly the peer average.
    assert short["weight"] < full["weight"]
    assert short["estimate"] < full["estimate"]
    assert (short["percentileHigh"] - short["percentileLow"]) >= (full["percentileHigh"] - full["percentileLow"])


def test_goalkeepers_and_thin_groups_say_why(client, auth, world, db):
    org = world["orgs"]["a"]
    event = "Invented League C 2030/31"
    keeper = _add_player(db, org, "Invented Keeper", age=30, position="GK", shots=0, n_matches=0)
    _season(db, keeper, org, event, group="goalkeeper", minutes=3000, goals=0, assists=0)
    _league(db, org, event, n=5, group="defender")
    lonely = _add_player(db, org, "Invented Defender", age=30, position=None, shots=0, n_matches=0)
    _season(db, lonely, org, event, group="defender", minutes=2000, goals=1, assists=1)
    db.flush()

    gk = _get(client, auth, keeper).json()["seasons"][0]
    assert gk["measures"] == [] and "Goalkeepers" in gk["note"]
    thin = _get(client, auth, lonely).json()["seasons"][0]
    assert thin["measures"] == [] and "Too few defenders" in thin["note"] and "(5;" in thin["note"]


def test_peers_without_analytics_consent_are_left_out(client, auth, world, db):
    org = world["orgs"]["a"]
    event = "Invented League D 2030/31"
    peers = _league(db, org, event, n=25)
    for p in peers[:3]:
        withdraw_analytics(db, p)
    player = _add_player(db, org, "Invented Forward", age=23, position=None, shots=1, n_matches=0)
    _season(db, player, org, event, group="forward", minutes=2000, goals=8, assists=3)
    db.flush()
    goals = next(m for m in _get(client, auth, player).json()["seasons"][0]["measures"] if m["key"] == "np_goals")
    assert goals["peers"] == 22


def test_without_analytics_consent_nobody_is_compared(client, auth, world, db):
    org = world["orgs"]["a"]
    event = "Invented League E 2030/31"
    _league(db, org, event)
    player = _add_player(db, org, "Invented Private", age=26, position=None, shots=1, n_matches=0)
    _season(db, player, org, event, group="forward", minutes=2000, goals=8, assists=3)
    withdraw_analytics(db, player)
    db.flush()
    body = _get(client, auth, player).json()
    assert body["seasons"] == [] and "consent" in body["note"]


def test_a_player_with_no_basic_seasons_gets_nothing(client, auth, world):
    body = _get(client, auth, world["players"]["adult_a"]).json()
    assert body == {"seasons": [], "note": None}


def test_a_player_the_caller_may_not_see_is_404(client, auth, world):
    assert _get(client, auth, world["players"]["minor_no_a"]).status_code == 404
