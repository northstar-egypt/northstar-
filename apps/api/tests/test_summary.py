"""The written profile summary (app/services/summary.py and GET /players/{id}/summary).

None of these tests need Ollama. The model is replaced by a function that returns chosen text,
because what is being tested is not whether the model writes well but whether the code ever
lets a number or a flag through that the page does not show. How the real model does on the
synthetic players is measured separately and reported in the PR that added this.
"""

from __future__ import annotations

import random
import re

import pytest

from app.models.enums import FlagType
from app.services import flags as flag_service
from app.services import summary

SHEET = [
    "A boy aged 17 years 3 months, playing football as CB.",
    "Latest height: 160.9 cm.",
    "Height has been measured 21 times, from May 2021 to May 2026.",
    "Height forecast for October 2027: 163.4 cm, with an 80% range of 161.9 to 164.9 cm.",
    "Height: 160.9 cm, percentile 12 against 46 boys aged 17 in the database "
    "(higher is better).",
    "Matches: 7 records, pass completion 71%.",
]


@pytest.fixture(autouse=True)
def fresh():
    """No summary cached by another test."""
    summary.clear_cache()
    yield
    summary.clear_cache()


@pytest.fixture
def model(monkeypatch):
    """Stand in for Ollama. Set `.reply` to the text, or to a function of the fact sheet."""

    class Fake:
        reply: object = "The player has been measured."
        seen: list[list[str]] = []

        def __call__(self, lines, *, model, url):
            self.seen.append(lines)
            return self.reply(lines) if callable(self.reply) else self.reply

    fake = Fake()
    fake.seen = []
    monkeypatch.setattr(summary, "ask_ollama", fake)
    return fake


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


def test_numbers_copied_from_the_facts_pass():
    text = (
        "The player is 17 years 3 months old and 160.9 cm tall, the 12th percentile among "
        "46 boys aged 17. The forecast for October 2027 is 163.4 cm, between 161.9 and "
        "164.9 cm (an 80% range). Pass completion is 71%."
    )
    assert summary.unsupported(text, SHEET) == []


def test_an_invented_number_is_caught():
    assert summary.unsupported("The player is 162.5 cm tall.", SHEET) == ["162.5"]


def test_a_fact_rounded_to_fewer_decimals_passes_but_a_shifted_one_does_not():
    assert summary.unsupported("About 161 cm tall.", SHEET) == []
    assert summary.unsupported("About 160 cm tall.", SHEET) == ["160"]


def test_number_words_are_checked_like_digits():
    assert summary.unsupported("Measured five times.", SHEET) == ["5"]
    assert summary.unsupported("Seven matches are recorded.", SHEET) == []


def test_a_flag_not_on_the_sheet_is_caught():
    """A caller without flag access gets no flag facts, and the reply may not supply one."""
    assert summary.unsupported("The player may be a late bloomer.", SHEET) == [
        "flag: late_bloomer"
    ]
    with_flag = [*SHEET, "Open flags: late bloomer."]
    assert summary.unsupported("The player is flagged as a late bloomer.", with_flag) == []


def test_any_number_that_gets_through_is_on_the_sheet():
    """The guarantee, tried against many corrupted replies rather than a few chosen ones.

    Each reply is the fact sheet itself with numbers randomly shifted, dropped in or rounded.
    Whatever `unsupported` lets through must consist only of numbers the sheet holds, or a
    sheet number rounded to fewer decimals.
    """
    rng = random.Random(20261006)
    text = " ".join(SHEET)
    sheet_values = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]

    let_through = 0
    for _ in range(500):
        def corrupt(match):
            roll = rng.random()
            if roll < 0.1:
                return f"{float(match.group()) + rng.choice([-1, 1]) * rng.choice([0.1, 1, 2]):.1f}"
            if roll < 0.15:
                return str(round(float(match.group())))
            return match.group()

        reply = re.sub(r"\d+(?:\.\d+)?", corrupt, text)
        if not summary.unsupported(reply, SHEET):
            let_through += 1
            for n in re.findall(r"\d+(?:\.\d+)?", reply):
                value = float(n)
                assert any(value == v or round(v) == value for v in sheet_values), n
    assert let_through > 0, "the check rejected every reply, including unchanged ones"


# ---------------------------------------------------------------------------
# The fact sheet is the caller's filtered profile
# ---------------------------------------------------------------------------


def _late_bloomer_flag(db, world):
    flag_service.upsert(
        db,
        player_id=world["players"]["adult_a"].id,
        flag_type=FlagType.LATE_BLOOMER.value,
        reason="Short for their age group and still growing.",
        evidence={"points": ["one"]},
        detector_name="test_detector",
        detector_version="v1",
    )


def test_a_caller_who_may_see_flags_gets_them_on_the_sheet(client, auth, world, db, model):
    _late_bloomer_flag(db, world)
    client.get(f"/players/{world['players']['adult_a'].id}/summary", headers=auth("coach_a"))
    assert any("late bloomer" in line for line in model.seen[-1])


def test_a_player_reading_their_own_summary_gets_no_flags(client, auth, world, db, model):
    """The profile withholds flags from the player themselves, so the summary must too."""
    _late_bloomer_flag(db, world)
    model.reply = "The player is a late bloomer."
    body = client.get(
        f"/players/{world['players']['adult_a'].id}/summary", headers=auth("player_self")
    ).json()
    assert not any("late bloomer" in line or "flag" in line.lower() for line in model.seen[-1])
    assert body["summary"] is None
    assert "not shown" in body["note"]


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


def test_a_checked_summary_is_returned(client, auth, world, model):
    model.reply = lambda lines: lines[0]
    body = client.get(
        f"/players/{world['players']['adult_a'].id}/summary", headers=auth("coach_a")
    ).json()
    assert body["summary"] == model.seen[-1][0]
    assert "checked" in body["note"]


def test_a_summary_with_an_invented_number_is_withheld(client, auth, world, model):
    model.reply = "The player scored 999 goals."
    body = client.get(
        f"/players/{world['players']['adult_a'].id}/summary", headers=auth("coach_a")
    ).json()
    assert body["summary"] is None
    assert "999" in body["note"]


def test_with_ollama_off_the_reason_is_given_and_the_profile_still_loads(
    client, auth, world, monkeypatch
):
    def down(*args, **kwargs):
        raise summary.OllamaUnavailable("The local language model is not running.")

    monkeypatch.setattr(summary, "ask_ollama", down)
    player_id = world["players"]["adult_a"].id
    body = client.get(f"/players/{player_id}/summary", headers=auth("coach_a")).json()
    assert body["summary"] is None
    assert "not running" in body["note"]
    assert client.get(f"/players/{player_id}/profile", headers=auth("coach_a")).status_code == 200


def test_the_unreachable_case_is_reported_without_a_fake(client, auth, world, monkeypatch):
    """The real client against a port nothing listens on: a reason, not a 500."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "ollama_url", "http://127.0.0.1:9")
    body = client.get(
        f"/players/{world['players']['adult_a'].id}/summary", headers=auth("coach_a")
    ).json()
    assert body["summary"] is None
    assert "not running" in body["note"]


def test_a_player_the_caller_may_not_see_is_404(client, auth, world, model):
    response = client.get(
        f"/players/{world['players']['minor_no_a'].id}/summary", headers=auth("scout")
    )
    assert response.status_code == 404
    assert model.seen == [], "the model must not be asked about a player the caller cannot see"


# ---------------------------------------------------------------------------
# The real model, on the synthetic players (opt in)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not __import__("os").environ.get("NORTHSTAR_SUMMARY_EVAL"),
    reason="set NORTHSTAR_SUMMARY_EVAL=1 to run the real model on the synthetic players",
)
def test_evaluation_with_the_model(db):
    """How the real model does: how many summaries are shown, how many withheld, and why.

        NORTHSTAR_SUMMARY_EVAL=1 pytest -s tests/test_summary.py -k evaluation

    Needs the synthetic dataset in Postgres and Ollama running with the model pulled. Reads
    every profile as the federation (which sees flags, so the sheet is at its fullest).
    Prints the counts and a few examples; it asserts only that the model answered.
    """
    import os
    import time

    from sqlalchemy import select

    from app.models.player import Player
    from app.models.user import User
    from app.services import views
    from app.services.access import load_caller

    size = int(os.environ.get("NORTHSTAR_SUMMARY_EVAL_SIZE", "40"))
    federation = db.execute(select(User).where(User.role == "federation")).scalars().first()
    if federation is None:
        pytest.skip("no synthetic dataset in this database")
    caller = load_caller(db, federation)
    players = list(db.execute(select(Player).order_by(Player.id)).scalars())
    sample = random.Random(20261006).sample(players, min(size, len(players)))

    shown, withheld, reasons, examples, seconds = 0, 0, {}, [], []
    for player in sample:
        start = time.perf_counter()
        result = summary.summarise(views.build_profile(db, caller, player))
        seconds.append(time.perf_counter() - start)
        if result.model is None:
            pytest.fail(f"the model did not answer: {result.note}")
        if result.text:
            shown += 1
            if len(examples) < 4:
                examples.append(result.text)
        else:
            withheld += 1
            for problem in re.findall(r"\((.*)\)\.$", result.note)[0].split(", "):
                kind = "flag" if problem.startswith("flag") else "number"
                reasons[kind] = reasons.get(kind, 0) + 1
            if len(examples) < 6:
                examples.append("WITHHELD: " + result.note)

    seconds.sort()
    print(f"\nmodel {summary.get_settings().ollama_model}, {len(sample)} players")
    print(f"shown {shown}, withheld {withheld} {reasons}")
    print(f"seconds per summary: median {seconds[len(seconds) // 2]:.1f}, max {seconds[-1]:.1f}")
    for text in examples:
        print("-", text)
