"""The assistant's fallback reader (app/services/rule_reader.py), through the assistant's own
cleaning (`read_by_rule`), so these are the readings the Ask screen would answer.

Questions here are written for the tests or taken from the development set. None is from the
held-out set in eval/assistant_questions.json, which is scored, never tuned on.
"""

from __future__ import annotations

import pytest

from app.services import assistant


@pytest.mark.parametrize(
    ("question", "expect"),
    [
        ("top 5 strikers for goals under 16",
         {"intent": "leaders", "position_group": "forward", "statistic": "goals", "age_to": 15}),
        ("best goalkeeper at passing accuracy",
         {"intent": "leaders", "position_group": "goalkeeper", "statistic": "pass_completion"}),
        ("who passes the ball the most among centre backs",
         {"intent": "leaders", "position_group": "defender", "statistic": "passes_attempted"}),
        ("which girls win the most points in ping pong",
         {"intent": "leaders", "sport": "table_tennis", "gender": "female", "statistic": "point_share"}),
        ("أكتر مدافع بيجري في الملعب",
         {"intent": "leaders", "position_group": "defender", "statistic": "distance_km"}),
        ("most tackles by a CB", {"intent": "leaders", "position_group": "defender", "statistic": "tackles"}),
    ],
)
def test_leaders(question, expect):
    reading = assistant.read_by_rule(question)
    for field, value in expect.items():
        assert getattr(reading, field) == value, field


def test_names_in_latin_drop_the_words_around_them():
    assert assistant.read_by_rule("show me Mostafa Ramy's stats").players == ["Mostafa Ramy"]
    reading = assistant.read_by_rule("Ahmed Tarek vs Mazen Ramy vs Seif Yasser")
    assert reading.intent == "compare"
    assert reading.players == ["Ahmed Tarek", "Mazen Ramy", "Seif Yasser"]


def test_names_in_arabic_after_the_word_that_introduces_them():
    reading = assistant.read_by_rule("قارن بين رامي باسم رياض و حسن جمال")
    assert reading.intent == "compare"
    assert reading.players == ["رامي باسم رياض", "حسن جمال"]
    reading = assistant.read_by_rule("مين بيلعب زي سيف ياسر شعبان")
    assert reading.intent == "similar" and reading.players == ["سيف ياسر شعبان"]


def test_one_name_is_that_player_and_like_makes_it_similar():
    assert assistant.read_by_rule("how many shots does Ali Adel take").intent == "player"
    assert assistant.read_by_rule("find me someone like Ahmed Tarek").intent == "similar"


@pytest.mark.parametrize(
    "question",
    ["what is Omar Hassan's salary", "is Karim Fathy injured", "who should we sign as a striker?"],
)
def test_what_the_records_cannot_answer_is_unsupported(question):
    assert assistant.read_by_rule(question).intent == "unsupported"


def test_the_flag_lists_and_ages_use_the_same_rules_as_a_model_reading():
    assert assistant.read_by_rule("show me the late bloomers").intent == "late_bloomers"
    assert assistant.read_by_rule("who broke out this season").intent == "breakouts"
    reading = assistant.read_by_rule("best 13 year old players")
    assert (reading.intent, reading.age_from, reading.age_to) == ("leaders", 13, 13)


def test_a_question_with_nothing_to_go_on_is_unsupported():
    assert assistant.read_by_rule("hello there").intent == "unsupported"
