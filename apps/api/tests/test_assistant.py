"""POST /assistant (app/services/assistant.py).

The model only reads the question, so these tests replace it with a fixed reading: CI has no
Ollama, and what is being tested is everything after the reading. How well the model reads
is measured separately, by eval/run_assistant_eval.py against Ollama.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.services import assistant
from tests.conftest import _add_player
from tests.test_gaps import league  # noqa: F401  (a fixture)


@pytest.fixture
def reads(monkeypatch):
    """Make the model read every question as `Reading(**fields)`."""

    def _reads(**fields):
        monkeypatch.setattr(
            assistant, "read_question", lambda question, **_: assistant.Reading(**fields)
        )

    return _reads


def _ask(client, auth, who="federation", question="anything"):
    return client.post("/assistant", json={"question": question}, headers=auth(who))


def test_leaders_are_the_explorers_leaders_with_the_reading_shown(client, auth, forwards, reads):
    reads(intent="leaders", sport="football", position_group="forward", statistic="shots")
    body = _ask(client, auth).json()
    assert body["rows"][0]["playerId"] == str(forwards[-1].id)
    assert body["rows"][0]["cells"][0] == forwards[-1].full_name
    assert len(body["rows"]) == 5
    assert body["columns"][-1] == "Percentile"
    assert "forwards" in body["chips"] and "shots" in body["chips"]
    assert "group=forward" in body["link"]["href"] and "view=leaders" in body["link"]["href"]
    assert "forwards, men and boys of every age" in body["answer"]


def test_without_a_statistic_the_leader_of_each_is_given(client, auth, forwards, reads):
    reads(intent="leaders", position_group="forward")
    body = _ask(client, auth).json()
    assert body["columns"] == ["Player", "Statistic", "Value", "Percentile"]
    # Tackles are equal for every forward here, so that board has no leader to list.
    assert "Tackles" not in {row["cells"][1] for row in body["rows"]}
    assert "Shots" in {row["cells"][1] for row in body["rows"]}


def test_a_goalkeeper_statistic_that_is_not_kept_is_said_so(client, auth, reads):
    reads(intent="leaders", position_group="goalkeeper", statistic="goals")
    body = _ask(client, auth).json()
    assert body["rows"] == [] and "no goalkeeping statistics" in body["answer"]


def test_one_named_player_gets_their_radar_with_the_asked_statistic_first(
    client, auth, forwards, reads
):
    reads(intent="player", players=[forwards[-1].full_name], statistic="key_passes")
    body = _ask(client, auth).json()
    assert body["rows"][0]["cells"][0] == "Key passes"
    assert body["link"]["href"] == f"/players/{forwards[-1].id}"
    assert "compared among forwards" in body["answer"]


def test_a_name_that_matches_several_asks_which(client, auth, forwards, reads):
    reads(intent="player", players=["Radar Forward"])
    body = _ask(client, auth).json()
    assert "Which one did you mean?" in body["answer"]
    assert len(body["rows"]) == assistant.MAX_CANDIDATES
    assert body["note"].startswith(f"Showing {assistant.MAX_CANDIDATES} of")


def test_a_name_that_matches_nobody_says_so(client, auth, reads):
    reads(intent="similar", players=["Nobody Byethisname"])
    assert "No player you may open matches" in _ask(client, auth).json()["answer"]


def test_a_scout_cannot_find_a_minor_hidden_from_scouts_by_name(
    client, auth, db, forwards, reads
):
    from app.models.consent import Consent
    from app.models.enums import ConsentPurpose

    hidden = forwards[-1]
    row = db.execute(
        select(Consent)
        .where(Consent.player_id == hidden.id)
        .where(Consent.purpose == ConsentPurpose.SCOUTING_VISIBILITY.value)
    ).scalar_one()
    row.granted = False
    db.flush()
    reads(intent="player", players=[hidden.full_name])
    body = _ask(client, auth, who="scout").json()
    assert "No player you may open matches" in body["answer"]
    assert str(hidden.id) not in str(body)


def test_similar_and_compare(client, auth, forwards, reads):
    reads(intent="similar", players=[forwards[4].full_name])
    similar = _ask(client, auth).json()
    assert similar["columns"][-1] == "Most alike on" and similar["rows"]

    reads(intent="compare", players=[forwards[-1].full_name, forwards[3].full_name])
    compared = _ask(client, auth).json()
    assert compared["columns"] == ["Statistic", forwards[-1].full_name, forwards[3].full_name]
    assert compared["link"]["href"].startswith("/compare?players=")


def test_a_question_the_records_cannot_answer_says_what_can_be_asked(client, auth, reads):
    reads(intent="unsupported")
    body = _ask(client, auth).json()
    assert body["rows"] == [] and body["answer"] == assistant.CAN_DO


def test_without_the_model_the_rules_read_and_the_answer_says_so(client, auth, forwards, monkeypatch):
    def down(question, **_):
        raise assistant.OllamaUnavailable("The local language model is not running.")

    monkeypatch.setattr(assistant, "read_question", down)
    response = _ask(client, auth, question="which strikers take the most shots")
    assert response.status_code == 200
    body = response.json()
    assert body["reader"] == "rules" and body["model"] is None
    assert body["reading"]["intent"] == "leaders"
    assert body["reading"]["positionGroup"] == "forward"
    assert body["reading"]["statistic"] == "shots"
    assert body["rows"], "the rules' reading is answered like the model's"


def test_assistant_reader_rules_never_asks_the_model(client, auth, monkeypatch):
    def never(question, **_):
        raise AssertionError("the model was asked")

    monkeypatch.setattr(assistant, "read_question", never)
    monkeypatch.setattr(assistant.get_settings(), "assistant_reader", "rules")
    body = _ask(client, auth, question="players similar to Hassan Gamal").json()
    assert body["reader"] == "rules"
    assert body["reading"]["intent"] == "similar"
    assert body["reading"]["players"] == ["Hassan Gamal"]


def test_with_the_model_the_answer_names_it(client, auth, reads):
    reads(intent="unsupported")
    body = _ask(client, auth).json()
    assert body["reader"] == "model" and body["model"]


def test_the_reading_is_cleaned_to_allowed_values():
    reading = assistant._clean(
        {
            "intent": "leaders", "sport": None, "gender": "robot", "position_group": "striker",
            "age_from": 17, "age_to": 14, "statistic": "point_share", "players": [" ", "Ali"],
        }
    )
    assert reading.sport == "table_tennis"  # from the statistic
    assert reading.gender is None and reading.position_group is None
    assert (reading.age_from, reading.age_to) == (14, 17)
    assert reading.players == ["Ali"]
    assert assistant._clean({"intent": "hack"}).intent == "unsupported"


@pytest.mark.parametrize(
    "question, ages",
    [
        ("top strikers under 16", (None, 15)),
        ("U14 midfielders", (None, 13)),
        ("U-17 forwards", (None, 16)),
        ("aged 14 to 16", (14, 16)),
        ("between 15 and 17", (15, 17)),
        ("16+", (16, None)),
        ("players 16 and over", (16, None)),
        ("over 16", (17, None)),
        ("17 and under", (None, 17)),
        ("15 year olds", (15, 15)),
        ("adults", (18, None)),
        ("مين أحسن هداف تحت ١٦ سنة", (None, 15)),
        ("فوق ١٨ سنة", (18, None)),
        ("لاعبين ١٤ سنة", (14, 14)),
        ("top 5 strikers", None),
        ("compare Ali and Omar", None),
    ],
)
def test_ages_are_read_by_rule(question, ages):
    assert assistant.ages_in(question) == ages


def test_a_gender_read_into_a_one_gender_sport_is_dropped():
    """Football registers boys and men only, so "girls" read into a football question would
    make the answer an error. The evaluation's scoring assumed this; the assistant now does it."""
    reading = assistant._clean({"intent": "leaders", "sport": "football", "gender": "female"})
    assert reading.gender is None
    kept = assistant._clean({"intent": "leaders", "sport": "table_tennis", "gender": "female"})
    assert kept.gender == "female"


# ---------------------------------------------------------------------------
# Answers drawn as cards, follow-up questions, and the two flag lists
# ---------------------------------------------------------------------------


def test_leaders_come_as_bars_with_questions_to_ask_next(client, auth, forwards, reads):
    reads(intent="leaders", sport="football", position_group="forward", statistic="shots")
    body = _ask(client, auth).json()
    (bars,) = body["blocks"]
    assert bars["type"] == "bars"
    # The bars are the table's rows, in the same order, with the same numbers.
    assert [i["playerId"] for i in bars["items"]] == [r["playerId"] for r in body["rows"]]
    assert bars["items"][0]["display"] == body["rows"][0]["cells"][3]
    top = forwards[-1].full_name
    assert body["followUps"][0] == f"How is {top} doing"
    assert len(body["followUps"]) == 3


def test_one_player_is_a_card_then_their_bars(client, auth, forwards, reads):
    reads(intent="player", players=[forwards[-1].full_name])
    body = _ask(client, auth).json()
    card, bars = body["blocks"]
    assert card["type"] == "people" and card["items"][0]["playerId"] == str(forwards[-1].id)
    assert bars["type"] == "bars" and bars["items"][0]["label"] == body["rows"][0]["cells"][0]
    assert body["followUps"] == [f"Players like {forwards[-1].full_name}"]


def test_a_pro_adult_is_answered_with_the_scouting_reports_verdict(client, auth, league, reads):  # noqa: F811
    _, strikers = league
    reads(intent="player", players=[strikers[8].full_name])
    body = _ask(client, auth, who="scout").json()
    verdict = next(b for b in body["blocks"] if b["type"] == "verdict")
    report = client.get(f"/players/{strikers[8].id}/scouting-report", headers=auth("scout")).json()["report"]
    assert verdict["grade"] == report["levelGrade"]
    assert verdict["recommendation"] == report["recommendation"]
    assert verdict["summary"] == report["summary"]
    assert body["link"]["href"] == f"/players/{strikers[8].id}/report"


def test_two_pros_are_compared_on_their_verdicts(client, auth, league, reads):  # noqa: F811
    _, strikers = league
    reads(intent="compare", players=[strikers[8].full_name, strikers[0].full_name])
    body = _ask(client, auth, who="scout").json()
    assert [b["type"] for b in body["blocks"]] == ["verdict", "verdict"]
    assert [b["playerId"] for b in body["blocks"]] == [str(strikers[8].id), str(strikers[0].id)]


def test_this_seasons_breakouts(client, auth, world, db, reads):
    from tests.test_pro_seasons import _season, _team, _write

    org = world["orgs"]["a"]
    previous, last = _team(db, org, "Ask Mate")
    rising = _add_player(db, org, "Ask Rising", age=20, position="LW", shots=1, n_matches=0)
    _write(db, rising, org, previous, _season(npxg=1.0, xa=0.5))
    _write(db, rising, org, last, _season(npxg=9.0, xa=4.5))
    db.flush()
    reads(intent="breakouts")
    body = _ask(client, auth, who="scout").json()
    assert "breakouts this season" in body["chips"]
    (people,) = body["blocks"]
    item = next(i for i in people["items"] if i["playerId"] == str(rising.id))
    assert "team's chances" in item["text"] and item["tags"] == ["breakout"]


def _late_bloomer_flag(db, player):
    from app.models.enums import FlagStatus, FlagType
    from app.models.flag import Flag

    db.add(Flag(
        player_id=player.id, type=FlagType.LATE_BLOOMER.value, status=FlagStatus.OPEN.value,
        confidence=0.8, reason="Small for 14 now; growth still to come.", evidence={},
        detector_name="test", detector_version="1", dedupe_key=f"test-lb-{player.id}",
    ))
    db.flush()


def test_late_bloomers_are_listed_for_staff_and_never_for_a_player(client, auth, db, forwards, reads):
    _late_bloomer_flag(db, forwards[2])
    reads(intent="late_bloomers")
    body = _ask(client, auth, who="federation").json()
    (people,) = body["blocks"]
    item = next(i for i in people["items"] if i["playerId"] == str(forwards[2].id))
    assert item["text"] == "Small for 14 now; growth still to come." and "late bloomer" in item["tags"]

    hidden = _ask(client, auth, who="player_self").json()
    assert hidden["blocks"] == [] and "not shown here" in hidden["answer"]
    assert str(forwards[2].id) not in str(hidden)


def test_a_flag_list_with_a_name_in_it_is_a_question_about_that_player():
    assert assistant._clean({"intent": "late_bloomers", "players": ["Omar Hassan"]}).intent == "player"
    assert assistant._clean({"intent": "breakouts", "players": ["A B", "C D"]}).intent == "compare"
    assert assistant._clean({"intent": "breakouts"}).intent == "breakouts"


@pytest.mark.parametrize(
    "question, topic",
    [
        ("who broke out this season", "breakouts"),
        ("any breakout players", "breakouts"),
        ("which pros stepped up", "breakouts"),
        ("مين اللي ظهر الموسم ده", "breakouts"),
        ("show me the late bloomers", "late_bloomers"),
        ("late developers", "late_bloomers"),
        ("مين نموه متأخر", "late_bloomers"),
        ("top 5 strikers for goals under 16", None),
        ("compare Ali Adel and Youssef Samir", None),
    ],
)
def test_the_flag_lists_are_recognised_by_rule(question, topic):
    assert assistant.topic_in(question) == topic


def test_a_flag_list_word_with_a_name_stays_a_question_about_the_player(monkeypatch):
    """"Is Omar Hassan a late bloomer" is about Omar Hassan: the rule only applies with no name."""
    import json as _json

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            reading = {"intent": "player", "players": ["Omar Hassan"]}
            return _json.dumps({"message": {"content": _json.dumps(reading)}}).encode()

    monkeypatch.setattr(assistant.urllib.request, "urlopen", lambda *a, **k: Reply())
    reading = assistant.read_question("is Omar Hassan a late bloomer", url="http://x")
    assert reading.intent == "player" and reading.players == ["Omar Hassan"]
    monkeypatch.setattr(
        Reply, "read",
        lambda self: _json.dumps({"message": {"content": _json.dumps({"intent": "leaders"})}}).encode(),
    )
    assert assistant.read_question("show me the late bloomers", url="http://x").intent == "late_bloomers"
