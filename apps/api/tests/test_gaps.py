"""Team gap analysis endpoints (app/routers/gaps.py, app/services/gaps.py).

A small league of its own, in a competition no seed uses, so the tests mean the same on CI's
empty database and on a seeded local one: nine clubs, one striker each, and the first club
the weakest at making chances.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from tests.conftest import _add_player, withdraw_analytics

LEAGUE = "Gap Test League"
SEASON = "2025/26"
START, END = date(2025, 8, 1), date(2026, 5, 31)


def _club(db, name):
    from app.models.organization import Organization

    org = Organization(id=uuid.uuid4(), name=name, type="club", sport="football", country="EG")
    db.add(org)
    db.flush()
    return org


def _team_season(db, org, xg_for):
    from app.models.team_season_stat import TeamSeasonStat

    db.add(TeamSeasonStat(
        organization_id=org.id, sport="football", competition=LEAGUE, season=SEASON, period_start=START,
        period_end=END, schema_ref="football.team_season.v1", source="api", metrics={
            "matches": 34, "wins": 12, "draws": 10, "losses": 12, "points": 46, "goals_for": 40,
            "goals_against": 40, "xg_for": xg_for, "xg_against": 40.0, "shots_for": 400, "shots_against": 400,
            "possession_pct": 50.0, "clean_sheets": 9, "home_points": 26, "away_points": 20,
            "goals_for_first_half": 18, "goals_against_first_half": 18, "goals_against_last_15": 8,
            "set_piece_goals_for": 9, "set_piece_goals_against": 9,
        }))


def _season(db, player, org, npxg):
    from app.models.performance_entry import PerformanceEntry

    db.add(PerformanceEntry(
        id=uuid.uuid4(), player_id=player.id, sport="football", period_type="season_aggregate",
        period_start=START, period_end=END, organization_id=org.id, event=f"{LEAGUE} {SEASON}",
        schema_ref="football.season_aggregate.v2", source="api", is_validated=True, metrics={
            "appearances": 25, "starts": 22, "minutes_played": 2000, "goals": 8, "penalty_goals": 0,
            "xg": npxg, "npxg": npxg, "assists": 2, "xa": 2.0, "shots": int(npxg * 8), "shots_on_target": 12,
            "key_passes": 15, "passes_attempted": 500, "passes_completed": 380, "crosses": 5,
            "dribbles_attempted": 30, "dribbles_completed": 15, "tackles": 10, "interceptions": 5, "duels": 200,
            "duels_won": 100, "aerial_duels": 60, "aerial_duels_won": 30, "clearances": 5, "yellow_cards": 2,
            "red_cards": 0,
        }))


@pytest.fixture
def league(db, world):
    clubs, strikers = [], []
    for i in range(9):
        org = _club(db, f"Gap Club {i}")
        _team_season(db, org, xg_for=30.0 + 3 * i)
        striker = _add_player(db, org, f"Gap Striker {i}", age=25, position="ST", shots=1, n_matches=0)
        _season(db, striker, org, npxg=4.0 + i)
        clubs.append(org)
        strikers.append(striker)
    db.flush()
    return clubs, strikers


def _get(client, auth, path, who="scout", **params):
    return client.get(path, headers=auth(who), params=params)


@pytest.mark.parametrize("who", ["coach_a", "player_self", "admin"])
def test_only_scouts_and_federation_staff_see_it(client, auth, world, who):
    assert _get(client, auth, "/gaps", who=who).status_code == 403
    assert _get(client, auth, "/gaps/national", who=who, need=["strikers:npxg_per_90"]).status_code == 403


def test_the_weak_club_is_offered_strikers_from_other_clubs(client, auth, league):
    clubs, strikers = league
    options = _get(client, auth, "/gaps").json()
    assert any(c["id"] == str(clubs[0].id) and c["seasons"] == [SEASON] for c in options["clubs"])

    body = _get(client, auth, f"/gaps/club/{clubs[0].id}", who="federation").json()
    assert body["club"]["season"] == SEASON and body["club"]["name"] == "Gap Club 0"
    chances = next(m for m in body["profile"] if m["key"] == "xg_for_per_game")
    assert chances["rank"] == 9 and chances["of"] == 9 and chances["weak"]
    need = next(n for n in chances["needs"] if n["group"] == "strikers")
    names = [c["fullName"] for c in need["candidates"]]
    assert names[0] == "Gap Striker 8" and "Gap Striker 0" not in names
    assert set(need["candidates"][0]["percentiles"]) == {"npxg_per_90", "shots_per_90"}

    coverage = next(g for g in body["coverage"] if g["group"] == "strikers")
    assert [p["fullName"] for p in coverage["players"]] == ["Gap Striker 0"]


def test_a_player_without_analytics_consent_is_not_ranked_or_proposed(client, auth, db, league):
    clubs, strikers = league
    withdraw_analytics(db, strikers[8])
    db.flush()
    body = _get(client, auth, f"/gaps/club/{clubs[0].id}").json()
    chances = next(m for m in body["profile"] if m["key"] == "xg_for_per_game")
    need = next(n for n in chances["needs"] if n["group"] == "strikers")
    assert "Gap Striker 8" not in [c["fullName"] for c in need["candidates"]]


def test_national_mode_takes_the_needs_it_is_given(client, auth, league):
    body = _get(client, auth, "/gaps/national", who="federation",
                need=["strikers:npxg_per_90"]).json()
    (need,) = body["needs"]
    names = [c["fullName"] for c in need["candidates"] + need["unranked"]]
    assert "Gap Striker 8" in names


def test_an_unknown_need_or_club_is_refused(client, auth, league):
    assert _get(client, auth, "/gaps/national", need=["goalies:saves"]).status_code == 422
    assert _get(client, auth, f"/gaps/club/{uuid.uuid4()}").status_code == 404
    clubs, _ = league
    assert _get(client, auth, f"/gaps/club/{clubs[0].id}", season="1999/00").status_code == 404
