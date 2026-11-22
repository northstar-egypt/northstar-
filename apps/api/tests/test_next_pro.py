"""GET /players/{id}/academy-matches and /pro-extras (app/services/next_pro.py, pro_extras.py).

What matters here is who appears and what is said when nothing can be shown: only academy
players the caller may see, only players with analytics consent, a note for goalkeepers and
for too little data, and nothing from the hand-made list unless it is on file. How stable the
matches are is measured by `python -m ml.next_pro_eval`.
"""

from __future__ import annotations

import json
import uuid
from datetime import date

import pytest

from tests.conftest import _add_player

SCHEMA = "football.season_aggregate.v2"
# Our own data source, so the pros made here are compared only with each other.
SOURCE = "import"


def _season(shots: int, assists: int) -> dict:
    return {
        "appearances": 30, "starts": 30, "minutes_played": 2700, "goals": shots // 5,
        "penalty_goals": 0, "xg": 4.0, "npxg": 4.0, "assists": assists, "xa": 2.0, "shots": shots,
        "shots_on_target": shots // 3, "key_passes": 20 + assists, "passes_attempted": 900,
        "passes_completed": 700, "crosses": 20, "dribbles_attempted": 30, "dribbles_completed": 15,
        "tackles": 20, "interceptions": 10, "duels": 200, "duels_won": 100, "aerial_duels": 40,
        "aerial_duels_won": 20, "clearances": 10, "yellow_cards": 3, "red_cards": 0,
    }


def _write(db, player, shots: int, assists: int) -> None:
    from app.models.performance_entry import PerformanceEntry

    db.add(PerformanceEntry(
        id=uuid.uuid4(), player_id=player.id, sport="football", period_type="season_aggregate",
        period_start=date(2025, 8, 1), period_end=date(2026, 5, 31),
        event="Test League 2025/26", metrics=_season(shots, assists), schema_ref=SCHEMA,
        source=SOURCE, is_validated=True,
    ))


@pytest.fixture
def league(db, world):
    """`adult_a` as a striker with nine league peers; youth strikers from `world` and a few more."""
    org = world["orgs"]["a"]
    star = world["players"]["adult_a"]
    _write(db, star, shots=110, assists=9)
    for i in range(9):
        mate = _add_player(db, org, f"League Striker {i}", age=26, position="ST", shots=1, n_matches=0)
        _write(db, mate, shots=40 + 8 * i, assists=i)
    keeper = _add_player(db, org, "League Keeper", age=28, position="GK", shots=0, n_matches=0)
    _write(db, keeper, shots=0, assists=0)
    for i in range(8):
        kid = _add_player(db, org, f"Academy Striker {i}", age=13, position="ST", shots=1 + i % 4)
        kid.tier = "youth"
    for name, shots in {"minor_ok_a": 4, "minor_no_a": 4}.items():
        from tests.test_similar import _matches

        _matches(db, world["players"][name], shots)
    db.flush()
    return {**world, "keeper": keeper}


def _get(client, auth, who, player, what="academy-matches"):
    return client.get(f"/players/{player.id}/{what}", headers=auth(who))


def _names(response):
    return {item["fullName"] for item in response.json()["items"]}


def test_a_coach_sees_only_their_own_academy_players(client, auth, league):
    body = _get(client, auth, "coach_a", league["players"]["adult_a"]).json()
    assert body["items"], body["note"]
    names = {i["fullName"] for i in body["items"]}
    # Academy A's coach: only academy A's children, never academy B's.
    assert all(n.startswith("Academy Striker") or n.endswith(" A") for n in names)
    assert all(0 <= i["percent"] <= 100 for i in body["items"])
    assert "not that the player will reach the same level" in body["note"]


def test_a_scout_never_sees_a_withheld_minor(client, auth, league):
    names = _names(_get(client, auth, "scout", league["players"]["adult_a"]))
    assert "Minor Blocked A" not in names and "Minor Blocked B" not in names


def test_without_analytics_consent_a_child_is_not_compared(client, auth, league, db):
    from tests.conftest import withdraw_analytics

    withdraw_analytics(db, league["players"]["minor_ok_a"])
    assert "Minor Consented A" not in _names(_get(client, auth, "federation", league["players"]["adult_a"]))


def test_a_goalkeeper_is_told_why_not_matched(client, auth, league):
    body = _get(client, auth, "federation", league["keeper"]).json()
    assert body["items"] == [] and "Goalkeepers are not matched" in body["note"]


def test_a_pro_with_no_league_season_is_told_why(client, auth, world):
    body = _get(client, auth, "federation", world["players"]["adult_b"]).json()
    assert body["items"] == [] and "900 minutes" in body["note"]


def test_extras_are_empty_without_a_list(client, auth, world, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "pro_extras_file", None)
    body = _get(client, auth, "scout", world["players"]["adult_a"], "pro-extras").json()
    assert body["managers"] == [] and body["videos"] == []


def test_extras_come_from_the_list_and_bad_video_ids_are_dropped(client, auth, world, monkeypatch, tmp_path):
    from app.config import get_settings

    player = world["players"]["adult_a"]
    path = tmp_path / "extras.json"
    path.write_text(json.dumps({"players": {f"player:{player.id}": {
        "managers": [{"name": "Coach One", "style": "Pressing"}, {"style": "no name, dropped"}],
        "videos": [{"title": "Good", "youtube": "abcDEF123_-"},
                   {"title": "Bad", "youtube": "\"><script>"}],
    }}}), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "pro_extras_file", str(path))
    body = _get(client, auth, "scout", player, "pro-extras").json()
    assert [m["name"] for m in body["managers"]] == ["Coach One"]
    assert [v["youtube"] for v in body["videos"]] == ["abcDEF123_-"]


def test_a_player_the_caller_may_not_see_is_404(client, auth, league):
    assert _get(client, auth, "scout", league["players"]["minor_no_a"]).status_code == 404
    assert _get(client, auth, "scout", league["players"]["minor_no_a"], "pro-extras").status_code == 404
