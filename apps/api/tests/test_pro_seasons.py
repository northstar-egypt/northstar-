"""GET /players/{id}/pro-seasons (app/services/pro.py, running ml/pro).

What the profile says about league seasons: a breakout only when a young player's share of
their team's chances clearly rose, finishing called above or below expected only outside the
range chance makes, trends only from enough minutes, and nothing without analytics consent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from tests.conftest import _add_player, withdraw_analytics

TODAY = date.today()
SCHEMA = "football.season_aggregate.v2"


@dataclass
class Season:
    label: str
    start: date
    end: date


def seasons_before(today: date) -> list[Season]:
    """The two completed August-to-May seasons before today, as the league loader dates them."""
    last = today.year if (today.month, today.day) >= (6, 1) else today.year - 1
    return [Season(f"{y - 1}/{str(y)[-2:]}", date(y - 1, 8, 1), date(y, 5, 31)) for y in (last - 1, last)]


def _season(minutes=2700, npxg=4.0, xa=2.0, goals=4, penalty_goals=0):
    shots = max(goals, 30)
    return {
        "appearances": 30, "starts": 30, "minutes_played": minutes, "goals": goals,
        "penalty_goals": penalty_goals, "xg": round(npxg + 0.76 * penalty_goals, 2), "npxg": npxg,
        "assists": 2, "xa": xa, "shots": shots, "shots_on_target": max(goals, 10), "key_passes": 20,
        "passes_attempted": 1200, "passes_completed": 1000, "crosses": 20, "dribbles_attempted": 30,
        "dribbles_completed": 15, "tackles": 40, "interceptions": 30, "duels": 200, "duels_won": 100,
        "aerial_duels": 40, "aerial_duels_won": 20, "clearances": 30, "yellow_cards": 3, "red_cards": 0,
    }


def _write(db, player, org, season, metrics):
    from app.models.performance_entry import PerformanceEntry

    db.add(PerformanceEntry(
        id=uuid.uuid4(), player_id=player.id, sport="football", period_type="season_aggregate",
        period_start=season.start, period_end=season.end, organization_id=org.id,
        event=f"Egyptian Premier League {season.label}", metrics=metrics, schema_ref=SCHEMA,
        source="api", is_validated=True,
    ))


def _team(db, org, name):
    """Eleven steady teammates over the last two seasons, so the team's totals are on record."""
    previous, last = seasons_before(TODAY)[-2:]
    for i in range(11):
        mate = _add_player(db, org, f"{name} {i}", age=27, position="CM", shots=1, n_matches=0)
        for season in (previous, last):
            _write(db, mate, org, season, _season())
    return previous, last


def _get(client, auth, player, who="federation"):
    return client.get(f"/players/{player.id}/pro-seasons", headers=auth(who))


def test_a_young_player_whose_share_of_the_chances_rose_is_a_breakout(client, auth, world, db):
    org = world["orgs"]["a"]
    previous, last = _team(db, org, "Pro Mate")
    rising = _add_player(db, org, "Pro Rising", age=21, position="LW", shots=1, n_matches=0)
    steady = _add_player(db, org, "Pro Steady", age=21, position="RW", shots=1, n_matches=0)
    _write(db, rising, org, previous, _season(npxg=2.0, xa=1.0))
    _write(db, rising, org, last, _season(npxg=6.0, xa=3.0))
    for season in (previous, last):
        _write(db, steady, org, season, _season())
    db.flush()

    body = _get(client, auth, rising).json()
    newest = body["seasons"][0]
    assert newest["season"] == last.label and newest["club"] == org.name
    assert newest["breakout"]["flagged"] is True
    assert "of the team's chances" in newest["breakout"]["reason"]
    assert _get(client, auth, steady).json()["seasons"][0]["breakout"]["flagged"] is False


def test_an_older_player_is_not_judged_for_a_breakout(client, auth, world, db):
    org = world["orgs"]["a"]
    previous, last = _team(db, org, "Pro Elder Mate")
    veteran = _add_player(db, org, "Pro Veteran", age=29, position="ST", shots=1, n_matches=0)
    _write(db, veteran, org, previous, _season(npxg=2.0, xa=1.0))
    _write(db, veteran, org, last, _season(npxg=6.0, xa=3.0))
    db.flush()
    breakout = _get(client, auth, veteran).json()["seasons"][0]["breakout"]
    assert breakout["flagged"] is False and breakout["considered"] is False
    assert "age window" in breakout["reason"]


def test_finishing_is_only_called_above_outside_the_range_chance_makes(client, auth, world, db):
    org = world["orgs"]["a"]
    _, last = seasons_before(TODAY)[-2:]
    hot = _add_player(db, org, "Pro Hot", age=26, position="ST", shots=1, n_matches=0)
    lucky = _add_player(db, org, "Pro Lucky", age=26, position="ST", shots=1, n_matches=0)
    quiet = _add_player(db, org, "Pro Quiet", age=26, position="CB", shots=1, n_matches=0)
    _write(db, hot, org, last, _season(npxg=8.0, goals=17))
    _write(db, lucky, org, last, _season(npxg=8.0, goals=10))
    _write(db, quiet, org, last, _season(npxg=0.8, goals=3))
    db.flush()

    hot_f = _get(client, auth, hot).json()["seasons"][0]["finishing"]
    assert hot_f["verdict"] == "above" and hot_f["low"] < 8 < hot_f["high"] < 17
    assert _get(client, auth, lucky).json()["seasons"][0]["finishing"]["verdict"] == "in line"
    quiet_f = _get(client, auth, quiet).json()["seasons"][0]["finishing"]
    assert quiet_f["verdict"] == "too few chances" and quiet_f["low"] is None


def test_trends_need_enough_minutes_in_both_seasons(client, auth, world, db):
    org = world["orgs"]["a"]
    previous, last = seasons_before(TODAY)[-2:]
    regular = _add_player(db, org, "Pro Regular", age=25, position="CM", shots=1, n_matches=0)
    sub = _add_player(db, org, "Pro Sub", age=25, position="CM", shots=1, n_matches=0)
    _write(db, regular, org, previous, _season(minutes=2000))
    _write(db, regular, org, last, _season(minutes=2500))
    _write(db, sub, org, previous, _season(minutes=600))
    _write(db, sub, org, last, _season(minutes=2500))
    db.flush()

    trends = _get(client, auth, regular).json()["trends"]
    assert len(trends) == 1 and trends[0]["season"] == last.label
    tackles = next(c for c in trends[0]["changes"] if c["key"] == "tackles")
    assert tackles["before"] == 1.8 and tackles["after"] == 1.44
    assert _get(client, auth, sub).json()["trends"] == []


def test_without_analytics_consent_nothing_is_judged(client, auth, world, db):
    org = world["orgs"]["a"]
    _, last = seasons_before(TODAY)[-2:]
    player = _add_player(db, org, "Pro Private", age=24, position="ST", shots=1, n_matches=0)
    _write(db, player, org, last, _season(npxg=8.0, goals=17))
    withdraw_analytics(db, player)
    db.flush()
    body = _get(client, auth, player).json()
    assert body["seasons"] == [] and body["career"] is None and "consent" in body["note"]


def test_a_player_with_no_league_seasons_is_told_so(client, auth, world):
    body = _get(client, auth, world["players"]["adult_a"]).json()
    assert body["seasons"] == [] and body["note"] == "No league seasons on record."


def test_a_player_the_caller_may_not_see_is_404(client, auth, world):
    assert _get(client, auth, world["players"]["minor_no_a"], who="scout").status_code == 404
