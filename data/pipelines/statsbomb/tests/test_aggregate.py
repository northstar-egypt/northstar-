"""data/pipelines/statsbomb/aggregate.py on one hand-made match in StatsBomb's format.

The match, teams and players are invented (no real data in the repository, ever): two teams of
two, a few events of each kind the aggregation counts, and a penalty shootout that must not.
"""

from __future__ import annotations

from data.pipelines.statsbomb import aggregate
from data.pipelines.statsbomb.countries import iso_code

HOME, AWAY = 1, 2
STRIKER, KEEPER, WINGER, DEFENDER = 11, 12, 21, 22


def _event(n, kind, minute, team, player=None, period=1, **extra):
    e = {"id": f"e{n}", "type": {"name": kind}, "period": period, "minute": minute, "second": 0,
         "team": {"id": team}, "possession_team": {"id": team}, "duration": 1.0}
    if player is not None:
        e["player"] = {"id": player}
    e.update(extra)
    return e


MATCH = {
    "match_id": 900, "match_date": "2030-01-01", "home_score": 2, "away_score": 1,
    "home_team": {"home_team_id": HOME, "home_team_name": "Invented Home"},
    "away_team": {"away_team_id": AWAY, "away_team_name": "Invented Away"},
}

LINEUPS = [
    {"team_id": HOME, "lineup": [
        {"player_id": STRIKER, "positions": [{"position": "Center Forward", "from": "00:00", "to": None,
                                              "from_period": 1, "start_reason": "Starting XI"}]},
        {"player_id": KEEPER, "positions": [{"position": "Goalkeeper", "from": "00:00", "to": "60:00",
                                             "from_period": 1, "start_reason": "Starting XI"}]},
    ]},
    {"team_id": AWAY, "lineup": [
        {"player_id": WINGER, "positions": [{"position": "Left Wing", "from": "30:00", "to": None,
                                             "from_period": 1, "start_reason": "Substitution - On"}]},
        {"player_id": DEFENDER, "positions": [{"position": "Left Center Back", "from": "00:00", "to": None,
                                               "from_period": 1, "start_reason": "Starting XI"}]},
        {"player_id": 23, "positions": []},  # on the bench all match
    ]},
]

EVENTS = [
    _event(1, "Pass", 10, HOME, KEEPER, pass_={}),
    _event(2, "Pass", 11, HOME, KEEPER, location=[90.0, 60.0],
           **{"pass": {"shot_assist": True, "goal_assist": True, "assisted_shot_id": "e3",
                       "end_location": [108.0, 40.0]}}),
    _event(3, "Shot", 11, HOME, STRIKER, location=[108.0, 40.0],
           shot={"outcome": {"name": "Goal"}, "statsbomb_xg": 0.4, "type": {"name": "Open Play"},
                 "body_part": {"name": "Head"}, "end_location": [120, 37, 2.0]}),
    _event(4, "Pass", 20, HOME, KEEPER, **{"pass": {"type": {"name": "Throw-in"}}}),
    _event(5, "Pass", 21, HOME, KEEPER, **{"pass": {"outcome": {"name": "Incomplete"}, "cross": True}}),
    _event(6, "Duel", 30, AWAY, DEFENDER, duel={"type": {"name": "Tackle"}, "outcome": {"name": "Won"}}),
    _event(7, "Duel", 31, AWAY, DEFENDER, duel={"type": {"name": "Aerial Lost"}}),
    _event(8, "Clearance", 32, AWAY, DEFENDER, clearance={"aerial_won": True}),
    _event(9, "Dribble", 50, AWAY, WINGER, period=2, dribble={"outcome": {"name": "Complete"}}),
    _event(10, "Shot", 80, AWAY, WINGER, period=2, location=[110.0, 30.0],
           shot={"outcome": {"name": "Goal"}, "statsbomb_xg": 0.76, "type": {"name": "Penalty"},
                 "body_part": {"name": "Right Foot"}}),
    _event(11, "Own Goal Against", 85, AWAY, DEFENDER, period=2),
    _event(12, "Foul Committed", 86, AWAY, DEFENDER, period=2, foul_committed={"card": {"name": "Yellow Card"}}),
    _event(13, "Interception", 88, HOME, STRIKER, period=2),
    _event(14, "Shot", 90, HOME, STRIKER, period=2, location=[100.0, 40.0],
           shot={"outcome": {"name": "Blocked"}, "statsbomb_xg": 0.05, "type": {"name": "Open Play"}}),
    # The shootout: not part of the match.
    _event(15, "Shot", 120, HOME, STRIKER, period=5, location=[108.0, 40.0],
           shot={"outcome": {"name": "Goal"}, "statsbomb_xg": 0.76, "type": {"name": "Penalty"}}),
]
EVENTS[0]["pass"] = EVENTS[0].pop("pass_")


def _read():
    return aggregate.read_match(MATCH, EVENTS, LINEUPS)


def test_goals_from_the_events_match_the_score_and_the_shootout_is_left_out():
    r = _read()
    assert r.event_goals == {HOME: 2, AWAY: 1}  # a header, an own goal; a penalty
    assert len(r.shots) == 3


def test_minutes_starts_and_who_did_not_play():
    r = _read()
    assert r.players[STRIKER]["minutes_played"] == 90 and r.players[STRIKER]["starts"] == 1
    assert r.players[KEEPER]["minutes_played"] == 60
    assert r.players[WINGER]["minutes_played"] == 60 and r.players[WINGER]["starts"] == 0
    assert 23 not in r.players
    assert r.player_team[WINGER] == AWAY


def test_shooting_counts_xg_and_xa():
    r = _read()
    s, k, w = r.players[STRIKER], r.players[KEEPER], r.players[WINGER]
    assert (s["shots"], s["shots_on_target"], s["goals"]) == (2, 1, 1)
    assert s["xg"] == 0.45 and s["npxg"] == 0.45
    assert (w["goals"], w["penalty_goals"], w["xg"], w["npxg"]) == (1, 1, 0.76, 0.0)
    assert (k["assists"], k["key_passes"]) == (1, 1) and k["xa"] == 0.4


def test_passes_leave_out_throw_ins():
    k = _read().players[KEEPER]
    assert (k["passes_attempted"], k["passes_completed"], k["crosses"]) == (3, 2, 1)


def test_duels_tackles_and_aerials():
    d = _read().players[DEFENDER]
    assert (d["tackles"], d["clearances"]) == (1, 1)
    # a tackle won, an aerial lost, an aerial won (the headed clearance)
    assert (d["duels"], d["duels_won"], d["aerial_duels"], d["aerial_duels_won"]) == (3, 2, 2, 1)
    assert d["yellow_cards"] == 1
    w = _read().players[WINGER]
    assert (w["dribbles_attempted"], w["dribbles_completed"], w["duels"], w["duels_won"]) == (1, 1, 1, 1)


def test_shots_on_the_platform_surface():
    shots = {s.shot_id: s for s in _read().shots}
    header = shots["e3"]
    assert (header.x, header.y) == (90.0, 50.0)
    assert (header.outcome, header.technique, header.situation, header.placement) == (
        "goal", "header", "open_play", "top_left")
    assert shots["e10"].situation == "penalty" and shots["e14"].outcome == "blocked"


def test_team_lines():
    r = _read()
    home, away = r.teams[HOME], r.teams[AWAY]
    assert (home["wins"], home["points"], home["home_points"], away["away_points"]) == (1, 3, 3, 0)
    assert home["goals_for_first_half"] == 1 and away["goals_against_first_half"] == 1
    assert away["goals_against_last_15"] == 1  # the own goal at 85
    assert away["set_piece_goals_for"] == 1  # the penalty
    assert round(home["xg_for"], 2) == 0.45 and home["shots_against"] == 1


def test_a_season_is_its_matches_summed_and_valid_shape():
    players, teams, positions = aggregate.season_totals([_read(), _read()])
    season = aggregate.player_season(players[STRIKER][HOME])
    assert season["appearances"] == 2 and season["goals"] == 2 and set(season) == set(aggregate.PLAYER_FIELDS)
    team = aggregate.team_season(teams[HOME])
    assert team["matches"] == 2 and 0 <= team["possession_pct"] <= 100
    assert aggregate.main_position(positions[DEFENDER]) == "CB"


def test_country_names_become_iso_codes():
    assert iso_code("Egypt") == "EG" and iso_code("Wales") == "GB"
    assert iso_code("Côte d'Ivoire") == "CI" and iso_code("Korea\xa0(South)") == "KR"
    assert iso_code("Atlantis") is None and iso_code(None) is None


def test_key_passes_are_kept_with_where_they_arrived_and_their_xa():
    (kp,) = _read().key_passes
    assert (kp.player_id, kp.team_id, kp.outcome) == (KEEPER, HOME, "assist")
    assert (kp.x, kp.y, kp.end_x, kp.end_y, kp.xa) == (75.0, 75.0, 90.0, 50.0, 0.4)


def test_touches_are_counted_on_a_12_by_8_grid():
    r = _read()
    # The striker's two shots from (108, 40) and (100, 40): both in column 10, row 4.
    assert r.touches[STRIKER][4 * 12 + 10] == 2
    assert sum(r.touches[STRIKER]) == 2  # the shootout penalty is not counted
    assert aggregate.touch_map(r.touches[STRIKER]) == {"z4_10": 2}
    season = aggregate.season_touches([_read(), _read()])
    assert season[STRIKER][HOME][4 * 12 + 10] == 4
    assert aggregate.zone([0, 0]) == 0 and aggregate.zone([120, 80]) == 95
