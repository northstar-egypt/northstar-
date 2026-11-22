"""Team gap analysis on a league with basic player seasons only (`football.season_basic.v1`,
FootyStats): app/services/gaps.py with `teamGaps.basic`.

An invented league in a competition no seed uses: nine clubs, the first the weakest at making
chances and the worst at allowing them. Each club has three forwards and three midfielders
(27 of each, enough to estimate rates: 20 peers are needed) and one defender (9, too few).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from tests.conftest import _add_player, withdraw_analytics

LEAGUE = "Gap Basic League"
SEASON = "2025/26"
START, END = date(2025, 8, 1), date(2026, 5, 31)
STAR = "Basic Forward 5-0"


def _club(db, name):
    from app.models.organization import Organization

    org = Organization(id=uuid.uuid4(), name=name, type="club", sport="football", country="EG")
    db.add(org)
    db.flush()
    return org


def _team_season(db, org, i):
    from app.models.team_season_stat import TeamSeasonStat

    db.add(TeamSeasonStat(
        organization_id=org.id, sport="football", competition=LEAGUE, season=SEASON, period_start=START,
        period_end=END, schema_ref="football.team_season.v1", source="footystats", metrics={
            "matches": 34, "wins": 12, "draws": 10, "losses": 12, "points": 46, "goals_for": 40,
            "goals_against": 40, "xg_for": 30.0 + 3 * i, "xg_against": 50.0 - 2 * i, "shots_for": 400,
            "shots_against": 400, "possession_pct": 50.0, "clean_sheets": 9, "home_points": 26, "away_points": 20,
            "goals_for_first_half": 18, "goals_against_first_half": 18, "goals_against_last_15": 8,
        }))


def _basic(db, player, org, group, *, minutes, goals, assists, pens=0):
    from app.models.performance_entry import PerformanceEntry

    metrics = {"position_group": group, "appearances": 30, "minutes_played": minutes, "goals": goals,
               "assists": assists, "penalty_goals": pens, "yellow_cards": 2, "red_cards": 0}
    if pens is None:  # FootyStats does not always publish it
        del metrics["penalty_goals"]
    db.add(PerformanceEntry(
        id=uuid.uuid4(), player_id=player.id, sport="football", period_type="season_aggregate",
        period_start=START, period_end=END, organization_id=org.id, event=f"{LEAGUE} {SEASON}",
        schema_ref="football.season_basic.v1", source="footystats", is_validated=True, metrics=metrics))


def _pro(db, org, name):
    return _add_player(db, org, name, age=25, position=None, shots=1, n_matches=0)


@pytest.fixture
def league(db, world):
    clubs, players = [], {}
    for i in range(9):
        org = _club(db, f"Basic Club {i}")
        _team_season(db, org, i)
        clubs.append(org)
        for f in range(3):
            name = f"Basic Forward {i}-{f}"
            players[name] = p = _pro(db, org, name)
            if name == STAR:
                _basic(db, p, org, "forward", minutes=3000, goals=25, pens=3, assists=10)
            elif i == 1 and f == 2:
                _basic(db, p, org, "forward", minutes=1800, goals=6, pens=None, assists=3)
            else:
                _basic(db, p, org, "forward", minutes=1500 + 100 * f, goals=(i + f) % 9, assists=(2 * i + f) % 6)
            name = f"Basic Midfielder {i}-{f}"
            players[name] = p = _pro(db, org, name)
            _basic(db, p, org, "midfielder", minutes=2000, goals=(i + f) % 4, assists=(i + 2 * f) % 7)
        name = f"Basic Defender {i}"
        players[name] = p = _pro(db, org, name)
        _basic(db, p, org, "defender", minutes=2500, goals=1, assists=i % 3)
    db.flush()
    return clubs, players


def _get(client, auth, path, who="scout", **params):
    response = client.get(path, headers=auth(who), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _metric(body, key):
    return next(m for m in body["profile"] if m["key"] == key)


def test_a_league_with_basic_seasons_only_is_analysed_on_the_basic_config(client, auth, league):
    clubs, _ = league
    body = _get(client, auth, f"/gaps/club/{clubs[0].id}")
    assert body["basic"] is True and body["minMinutes"] == 90
    assert [g["group"] for g in body["coverage"]] == ["forwards", "midfielders", "defenders"]
    forwards = next(g for g in body["coverage"] if g["group"] == "forwards")
    assert {p["fullName"] for p in forwards["players"]} == {f"Basic Forward 0-{f}" for f in range(3)}
    assert all(set(p["percentiles"]) == {"np_goals_per_90", "assists_per_90"} for p in forwards["players"])
    assert all(v is not None for p in forwards["players"] for v in p["percentiles"].values())
    # Nine defenders are too few to tell real differences from chance: no percentile at all.
    defenders = next(g for g in body["coverage"] if g["group"] == "defenders")
    assert [p["percentiles"] for p in defenders["players"]] == [{"assists_per_90": None}]


def test_chances_made_proposes_forwards_and_midfielders_from_other_clubs(client, auth, league):
    clubs, _ = league
    body = _get(client, auth, f"/gaps/club/{clubs[0].id}", who="federation")
    chances = _metric(body, "xg_for_per_game")
    assert chances["rank"] == 9 and chances["weak"]
    assert [(n["group"], n["basic"]) for n in chances["needs"]] == [("forwards", True), ("midfielders", True)]
    forwards = chances["needs"][0]
    names = [c["fullName"] for c in forwards["candidates"]]
    assert names[0] == STAR
    assert not any(n.startswith("Basic Forward 0-") for n in names)
    assert set(forwards["candidates"][0]["percentiles"]) == {"np_goals_per_90", "assists_per_90"}


def test_a_weakness_basic_data_cannot_answer_says_so(client, auth, league):
    clubs, _ = league
    allowed = _metric(_get(client, auth, f"/gaps/club/{clubs[0].id}"), "xg_against_per_game")
    assert allowed["weak"] and allowed["needs"] == []
    assert "basic" in allowed["noPlayerLink"]


def test_the_numbers_are_the_talent_estimates_on_the_profile(client, auth, league):
    clubs, players = league
    body = _get(client, auth, f"/gaps/club/{clubs[0].id}")
    star = next(c for c in _metric(body, "xg_for_per_game")["needs"][0]["candidates"] if c["fullName"] == STAR)
    profile = _get(client, auth, f"/players/{players[STAR].id}/estimates")
    (season,) = [s for s in profile["seasons"] if s["competition"] == LEAGUE]
    measures = {m["key"]: m for m in season["measures"]}
    # Non-penalty: 22 goals in 3,000 minutes, pulled towards the forwards' rate.
    assert star["values"]["np_goals_per_90"] == pytest.approx(measures["np_goals"]["estimate"], abs=1e-3)
    assert star["values"]["np_goals_per_90"] < 22 / (3000 / 90)
    assert star["percentiles"]["np_goals_per_90"] == measures["np_goals"]["percentile"]
    assert star["percentiles"]["assists_per_90"] == measures["assists"]["percentile"]
    assert star["population"] == 27


def test_a_missing_penalty_count_gives_no_goals_estimate_but_keeps_assists(client, auth, league):
    clubs, _ = league
    body = _get(client, auth, f"/gaps/club/{clubs[1].id}")
    forwards = next(g for g in body["coverage"] if g["group"] == "forwards")
    unknown = next(p for p in forwards["players"] if p["fullName"] == "Basic Forward 1-2")
    assert unknown["percentiles"]["np_goals_per_90"] is None
    assert unknown["percentiles"]["assists_per_90"] is not None


def test_a_player_without_analytics_consent_is_not_ranked_or_proposed(client, auth, db, league):
    clubs, players = league
    withdraw_analytics(db, players[STAR])
    db.flush()
    body = _get(client, auth, f"/gaps/club/{clubs[0].id}")
    forwards = _metric(body, "xg_for_per_game")["needs"][0]
    assert STAR not in [c["fullName"] for c in forwards["candidates"] + forwards["unranked"]]
    assert forwards["candidates"][0]["population"] == 26


def test_national_mode_takes_basic_and_full_needs_together(client, auth, league):
    body = _get(client, auth, "/gaps/national", who="federation",
                need=["forwards:np_goals_per_90,assists_per_90", "strikers:npxg_per_90"])
    forwards, strikers = body["needs"]
    assert forwards["basic"] is True and strikers["basic"] is False
    assert STAR in [c["fullName"] for c in forwards["candidates"]]
    assert not any(c["fullName"].startswith("Basic ") for c in strikers["candidates"] + strikers["unranked"])


def test_a_basic_need_with_a_full_statistic_is_refused(client, auth, league):
    response = client.get("/gaps/national", headers=auth("scout"), params={"need": ["forwards:npxg_per_90"]})
    assert response.status_code == 422


def test_the_options_list_the_basic_groups_and_their_rules(client, auth, league):
    options = _get(client, auth, "/gaps")
    groups = {g["key"]: g for g in options["groups"]}
    assert groups["forwards"]["basic"] is True and groups["strikers"]["basic"] is False
    attributes = {a["key"]: a for a in options["attributes"]}
    assert attributes["np_goals_per_90"]["estimated"] is True and attributes["npxg_per_90"]["estimated"] is False
    assert (options["basicMinMinutes"], options["basicMinPeers"]) == (90, 20)


def test_twenty_peers_are_needed_besides_the_player_as_on_the_profile(client, auth, db, world):
    """20 forwards: each has 19 others, one too few, so nobody is ranked; the 21st changes that."""
    from app.models.team_season_stat import TeamSeasonStat

    org = _club(db, "Edge Club")
    db.add(TeamSeasonStat(
        organization_id=org.id, sport="football", competition="Gap Edge League", season=SEASON,
        period_start=START, period_end=END, schema_ref="football.team_season.v1", source="footystats",
        metrics={"matches": 34, "wins": 12, "draws": 10, "losses": 12, "points": 46, "goals_for": 40,
                 "goals_against": 40, "xg_for": 40.0, "xg_against": 40.0, "shots_for": 400, "shots_against": 400,
                 "possession_pct": 50.0, "clean_sheets": 9, "home_points": 26, "away_points": 20,
                 "goals_for_first_half": 18, "goals_against_first_half": 18, "goals_against_last_15": 8}))

    def forward(n):
        from app.models.performance_entry import PerformanceEntry

        p = _pro(db, org, f"Edge Forward {n}")
        db.add(PerformanceEntry(
            id=uuid.uuid4(), player_id=p.id, sport="football", period_type="season_aggregate", period_start=START,
            period_end=END, organization_id=org.id, event=f"Gap Edge League {SEASON}",
            schema_ref="football.season_basic.v1", source="footystats", is_validated=True,
            metrics={"position_group": "forward", "appearances": 25, "minutes_played": 2000, "goals": n % 7,
                     "assists": n % 4, "penalty_goals": 0, "yellow_cards": 1, "red_cards": 0}))
        db.flush()
        return p

    first = [forward(n) for n in range(20)]

    def ranked():
        coverage = _get(client, auth, f"/gaps/club/{org.id}")["coverage"]
        players = next(g for g in coverage if g["group"] == "forwards")["players"]
        return {v is not None for p in players for v in p["percentiles"].values()}

    assert ranked() == {False}
    assert "19; 20 are needed" in _get(client, auth, f"/players/{first[0].id}/estimates")["seasons"][0]["note"]
    forward(20)
    assert ranked() == {True}
