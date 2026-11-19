"""data/pipelines/footystats/transform.py on invented rows in FootyStats' format.

No real player, club or match appears here: every name and number is made up.
"""

from __future__ import annotations

from datetime import date

from data.pipelines.footystats import transform as t


def _player(**over):
    row = {"id": 1, "full_name": "Invented Player", "position": "Midfielder", "appearances_overall": 20,
           "minutes_played_overall": 1500, "goals_overall": 4, "assists_overall": 3, "penalty_goals": 1,
           "penalty_misses": 0, "yellow_cards_overall": 2, "red_cards_overall": 0, "clean_sheets_overall": 5,
           "conceded_overall": 18}
    row.update(over)
    return row


def test_player_season_keeps_only_published_fields():
    metrics, why = t.player_season(_player())
    assert why is None
    assert metrics == {"appearances": 20, "minutes_played": 1500, "goals": 4, "assists": 3, "penalty_goals": 1,
                       "penalty_misses": 0, "yellow_cards": 2, "red_cards": 0, "clean_sheets": 5,
                       "goals_conceded": 18}


def test_unknown_optional_field_is_left_out_not_zeroed():
    metrics, _ = t.player_season(_player(penalty_misses=-1, conceded_overall=None))
    assert "penalty_misses" not in metrics and "goals_conceded" not in metrics


def test_rejections_say_why():
    assert t.player_season(_player(position="Coach")) == (None, "not a player (coach)")
    assert t.player_season(_player(minutes_played_overall=0, goals_overall=0, assists_overall=0))[1] == "never played (0 minutes)"
    assert t.player_season(_player(goals_overall=-1))[1] == "missing goals"


def _match(mid, home, away, hg, ag, h_times=(), a_times=(), status="complete", **over):
    m = {"id": mid, "status": status, "homeID": home, "awayID": away, "homeGoalCount": hg, "awayGoalCount": ag,
         "homeGoals_timings": list(h_times), "awayGoals_timings": list(a_times), "date_unix": 1900000000 + mid,
         "team_a_xg": 1.5, "team_b_xg": 0.5, "team_a_shots": 12, "team_b_shots": 6,
         "team_a_possession": 60, "team_b_possession": 40}
    m.update(over)
    return m


MATCHES = [
    _match(1, 10, 20, 2, 1, ["12", "45+2"], ["90+3"]),
    _match(2, 20, 10, 0, 0),
    _match(3, 10, 20, 1, 3, ["46"], ["5", "80", "77"], team_a_xg=0.9, team_b_xg=2.1),
    _match(4, 10, 20, 9, 9, status="canceled"),
]


def test_team_seasons_from_matches():
    seasons, problems = t.team_seasons(MATCHES)
    assert problems == []
    a, b = seasons[10], seasons[20]
    assert (a["matches"], a["wins"], a["draws"], a["losses"], a["points"]) == (3, 1, 1, 1, 4)
    assert (b["matches"], b["wins"], b["draws"], b["losses"], b["points"]) == (3, 1, 1, 1, 4)
    assert (a["goals_for"], a["goals_against"]) == (3, 4)
    assert a["home_points"] == 3 and a["away_points"] == 1 and b["home_points"] == 1 and b["away_points"] == 3
    # '45+2' is first half, '46' is not; '90+3', '80' and '77' are in the last 15 minutes.
    assert a["goals_for_first_half"] == 2
    assert a["goals_against_first_half"] == 1
    assert a["goals_against_last_15"] == 3
    assert a["xg_for"] == round(1.5 + 0.5 + 0.9, 2) and a["xg_against"] == round(0.5 + 1.5 + 2.1, 2)
    assert a["shots_for"] == 12 + 6 + 12
    assert a["possession_pct"] == round((60 + 40 + 60) / 3, 1)
    assert a["clean_sheets"] == 1 and b["clean_sheets"] == 1
    assert "set_piece_goals_for" not in a


def test_a_match_missing_xg_rejects_both_teams():
    seasons, problems = t.team_seasons(MATCHES[:2] + [_match(5, 10, 30, 1, 0, team_b_xg=-1), _match(6, 20, 40, 1, 0)])
    assert 10 not in seasons and 30 not in seasons and 20 in seasons
    assert problems == ["match 5: xG, shots or possession missing"]


def test_reconcile_against_published_totals():
    seasons, _ = t.team_seasons(MATCHES)
    good = {"seasonMatchesPlayed_overall": 3, "seasonWinsNum_overall": 1, "seasonGoals_overall": 3,
            "seasonConceded_overall": 4, "seasonCS_overall": 1}
    assert t.reconcile(seasons[10], good) == []
    assert t.reconcile(seasons[10], {**good, "seasonGoals_overall": 5}) == [
        "goals_for: 3 from matches, 5 in FootyStats' totals"]
    # A total FootyStats marks unknown is not compared.
    assert t.reconcile(seasons[10], {**good, "seasonCS_overall": -1}) == []


def test_small_helpers():
    assert t.season_label("2024/2025") == "2024/25" and t.season_label("2031") == "2031"
    assert t.day(-1) is None and t.day(0) is None and t.day(86400) == date(1970, 1, 2)
    assert t.country_code("Egypt") == "EG" and t.country_code("Republic of Ireland") == "IE"
    assert t.country_code("USA") == "US" and t.country_code("Nowhere Land") is None
    assert t.POSITIONS.get("Goalkeeper") == "GK" and t.POSITIONS.get("Defender") is None
    assert t.season_span(MATCHES) == (t.day(1900000001), t.day(1900000003))
