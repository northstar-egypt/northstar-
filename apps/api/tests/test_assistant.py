"""POST /assistant (app/services/assistant.py).

The model only reads the question, so these tests replace it with a fixed reading: CI has no
Ollama, and what is being tested is everything after the reading. How well the model reads
is measured separately, by eval/run_assistant_eval.py against Ollama.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.services import assistant
from tests.test_radar import _add_player, forwards, only  # noqa: F401  (fixtures)


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


def test_no_language_model_is_a_503_with_the_reason(client, auth, monkeypatch):
    def down(question, **_):
        raise assistant.OllamaUnavailable("The local language model is not running.")

    monkeypatch.setattr(assistant, "read_question", down)
    response = _ask(client, auth)
    assert response.status_code == 503 and "not running" in response.json()["detail"]


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
