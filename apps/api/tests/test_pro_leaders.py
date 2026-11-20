"""Leaders of a professional league season (app/services/pro_leaders.py).

The ranking is tested on invented rows with no database. The last tests write invented basic
seasons for the access fixture's players and ask through POST /assistant, to show the answer
holds only players the caller may open.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.services import assistant, pro_leaders
from app.services.pro_leaders import SeasonLine, rank, resolve

START = date(2023, 8, 11)


def line(name, *, goals=0, assists=0, minutes=900, apps=10, group="forward", born=date(2000, 1, 1)):
    return SeasonLine(
        player_id=name, name=name, club="Club", season_start=START, date_of_birth=born,
        metrics={"position_group": group, "appearances": apps, "minutes_played": minutes,
                 "goals": goals, "assists": assists, "yellow_cards": 0, "red_cards": 0},
    )


def names(body):
    return [leader["name"] for leader in body["leaders"]]


def test_ranks_highest_first_with_ties_broken_by_fewer_minutes():
    body = rank([line("A", goals=5, minutes=2000), line("B", goals=9), line("C", goals=5, minutes=1000)],
                statistic="goals")
    assert names(body) == ["B", "C", "A"]
    assert body["leaders"][0]["value"] == 9


def test_per_90_needs_450_minutes_and_says_how_many_were_left_out():
    cameo = line("Cameo", goals=2, minutes=40)   # 4.5 per 90 from 40 minutes
    regular = line("Regular", goals=10, minutes=1800)
    body = rank([cameo, regular], statistic="goals_per_90")
    assert names(body) == ["Regular"]
    assert body["leaders"][0]["value"] == 0.5
    assert body["left_out"] == {"under 450 minutes": 1}


def test_exactly_450_minutes_is_enough():
    assert names(rank([line("A", assists=1, minutes=450)], statistic="assists_per_90")) == ["A"]


def test_position_group_is_the_seasons_own_label():
    body = rank([line("F", goals=3), line("D", goals=1, group="defender")],
                statistic="goals", position_group="defender")
    assert names(body) == ["D"]


def test_age_is_on_the_seasons_first_day():
    # Born the day after the season starts: still 22 for this season, though 23 by its end.
    turns_23_later = line("Late", goals=4, born=date(2000, 8, 12))
    turned_23 = line("Early", goals=6, born=date(2000, 8, 11))
    body = rank([turns_23_later, turned_23], statistic="goals", age_to=22)
    assert names(body) == ["Late"]
    assert body["leaders"][0]["age"] == 22


def test_no_birthday_is_left_out_of_an_age_ranking_and_counted():
    unknown = line("Unknown", goals=20, born=None)
    body = rank([unknown, line("Known", goals=1)], statistic="goals", age_from=18)
    assert names(body) == ["Known"]
    assert body["left_out"] == {"no date of birth on record": 1}
    # Without an age filter the same player is ranked, with no age shown.
    assert rank([unknown], statistic="goals")["leaders"][0]["age"] is None


def test_only_published_statistics_are_ranked():
    with pytest.raises(ValueError):
        rank([line("A")], statistic="xg")


def test_limit():
    body = rank([line(str(i), goals=i) for i in range(15)], statistic="goals")
    assert len(body["leaders"]) == pro_leaders.LIMIT and body["considered"] == 15


ON_RECORD = [
    ("England Premier League", "2024/25", date(2025, 5, 25)),
    ("England Premier League", "2023/24", date(2024, 5, 19)),
    ("Mexico Liga MX", "2019/20", date(2020, 3, 15)),
]


def test_resolve_a_named_league_and_season():
    assert resolve(ON_RECORD, "england_premier_league", "2023/24") == ("England Premier League", "2023/24")
    assert resolve(ON_RECORD, "liga_mx", None) == ("Mexico Liga MX", "2019/20")


def test_no_season_means_the_latest():
    assert resolve(ON_RECORD, "england_premier_league", None)[1] == "2024/25"


def test_a_season_not_loaded_lists_the_ones_that_are():
    with pytest.raises(pro_leaders.ProLeadersError, match="2024/25, 2023/24"):
        resolve(ON_RECORD, "england_premier_league", "2010/11")


def test_a_league_not_loaded_says_so():
    with pytest.raises(pro_leaders.ProLeadersError, match="No Egyptian Premier League seasons"):
        resolve(ON_RECORD, "egyptian_premier_league", None)


def test_no_league_named_is_asked_when_two_could_be_meant():
    with pytest.raises(pro_leaders.ProLeadersError, match="Which league"):
        resolve(ON_RECORD, None, None)
    # A season only one league has settles it.
    assert resolve(ON_RECORD, None, "2019/20")[0] == "Mexico Liga MX"


def test_egypt_is_not_read_as_the_english_premier_league():
    assert pro_leaders.league_of("Egyptian Premier League") == "egyptian_premier_league"
    assert pro_leaders.league_of("England Premier League") == "england_premier_league"


# ---------------------------------------------------------------------------
# Through the Ask screen, with the database
# ---------------------------------------------------------------------------

@pytest.fixture
def pro_season(db, world):
    """Invented basic seasons for three of the access fixture's players."""
    from app.models.performance_entry import PerformanceEntry

    goals = {"adult_a": 7, "adult_b": 3, "minor_no_a": 12}
    for key, n in goals.items():
        db.add(PerformanceEntry(
            id=uuid.uuid4(), player_id=world["players"][key].id, sport="football",
            period_type="season_aggregate", period_start=START, period_end=date(2024, 5, 19),
            event="England Premier League 2023/24", schema_ref=pro_leaders.BASIC, source="footystats",
            is_validated=True,
            metrics={"position_group": "forward", "appearances": 20, "minutes_played": 1500,
                     "goals": n, "assists": 1, "yellow_cards": 0, "red_cards": 0},
        ))
    db.flush()
    return world


@pytest.fixture
def reads(monkeypatch):
    def _reads(**fields):
        monkeypatch.setattr(assistant, "read_question", lambda question, **_: assistant.Reading(**fields))
    return _reads


def _ask(client, auth, who):
    return client.post("/assistant", json={"question": "top scorers"}, headers=auth(who)).json()


def test_a_scout_does_not_see_a_minor_without_scouting_consent(client, auth, pro_season, reads):
    reads(intent="pro_leaders", league="england_premier_league", season="2023/24", statistic="goals")
    body = _ask(client, auth, "scout")
    shown = [row["cells"][0] for row in body["rows"]]
    players = pro_season["players"]
    assert shown == [players["adult_a"].full_name, players["adult_b"].full_name]
    assert "England Premier League 2023/24" in body["answer"]
    assert "not players you may open" in body["note"]


def test_a_coach_sees_only_their_own_squad(client, auth, pro_season, reads):
    reads(intent="pro_leaders", league="england_premier_league", season=None, statistic="goals")
    shown = [row["cells"][0] for row in _ask(client, auth, "coach_a")["rows"]]
    players = pro_season["players"]
    assert shown == [players["minor_no_a"].full_name, players["adult_a"].full_name]


def test_a_statistic_the_source_does_not_publish_is_answered_with_why(client, auth, pro_season, reads):
    reads(intent="pro_leaders", league="england_premier_league", season="2023/24", statistic="xg")
    body = _ask(client, auth, "federation")
    assert body["rows"] == []
    assert "not expected goals (xG)" in body["answer"]


# ---------------------------------------------------------------------------
# Reading a pro question, by rule (app/services/assistant.py, `pro_in`). Written for the tests;
# none is from the held-out half of eval/assistant_questions.json.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("text", "season"), [
    ("2021/22", "2021/22"), ("2021-22", "2021/22"), ("2021-2022", "2021/22"), ("21/22", "2021/22"),
    ("موسم ٢٠٢١/٢٢", "2021/22"), ("aged 15-16", None), ("2021/23", None), ("under 16", None),
])
def test_season_in(text, season):
    assert assistant.season_in(text) == season


@pytest.mark.parametrize(("question", "expect"), [
    ("leading scorer, Premier League 2020/21",
     {"intent": "pro_leaders", "league": "england_premier_league", "season": "2020/21", "statistic": "goals"}),
    ("assists per 90 for defenders in the Egyptian league",
     {"intent": "pro_leaders", "league": "egyptian_premier_league", "season": None,
      "statistic": "assists_per_90", "position_group": "defender"}),
    ("most matches played Liga MX 2019/20",
     {"intent": "pro_leaders", "league": "liga_mx", "statistic": "appearances"}),
    ("مين جاب أهداف أكتر في الدوري الإنجليزي",
     {"intent": "pro_leaders", "league": "england_premier_league", "statistic": "goals"}),
    # Academy questions stay academy questions.
    ("top scorers under 16", {"intent": "leaders", "league": None, "statistic": "goals"}),
    ("best passers aged 15-16", {"intent": "leaders", "season": None}),
])
def test_pro_questions_read_by_rule(question, expect):
    reading = assistant.read_by_rule(question).__dict__
    assert {k: reading[k] for k in expect} == expect


def test_a_named_player_in_a_league_is_still_about_that_player():
    reading = assistant.read_by_rule("how is Omar Hassan doing in the Premier League 2023/24")
    assert reading.intent == "player" and reading.players == ["Omar Hassan"]
