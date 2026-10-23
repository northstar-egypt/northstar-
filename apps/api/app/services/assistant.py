"""The assistant: a question in plain words, answered from the platform's own numbers.

The language model reads the question. It does not answer it. The design keeps those apart,
for the same reason as the profile summary (services/summary.py), and more strictly:

1. **The model reads.** A local Ollama model (`OLLAMA_ASSISTANT_MODEL`, qwen2.5:3b by
   default, temperature 0, with worked examples in `EXAMPLES`) turns the
   question into a fixed form (`READING_SCHEMA`): what is being asked (`intent`), and the
   sport, gender, position group, ages, statistic and player names it mentions. Ollama is
   told to answer in exactly that JSON shape, and `_clean` throws away anything outside the
   allowed values, then makes the intent agree with the names read. Ages are read by fixed
   rules (`ages_in`), not by the model. English and Arabic both work.
2. **The platform answers.** The reading runs the same services the screens use, as the
   person asking: the explorer's leaders, the radar, similar players. So the answer can hold
   only what that person could open on a screen, and the consent and percentile rules are
   those services' own.
3. **No number is written by the model.** The answer is built from the services' results by
   `_answer_*`. There is nothing for a model to invent and nothing to check afterwards.

The reading is sent back with the answer and the screen prints it ("How this was read"), so a
misreading is visible rather than silent, and each answer links to the screen that shows the
same thing with its filters, where the reading can be corrected by hand.

How often the reading is right is measured by `eval/run_assistant_eval.py` against questions
with known readings, a development set the prompt was written against and a held-out set it
was not. The numbers are in ml/README.md, "Assistant".
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from datetime import date
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app import ages, names, sports
from app.config import get_settings
from app.models.player import Player
from app.services import explore, radar, similar
from app.services.access import Caller, may_view, visible_players
from app.services.cohort import age_label

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 120

INTENTS = ("leaders", "player", "similar", "compare", "unsupported")
GROUPS = ("goalkeeper", "defender", "midfielder", "forward")
STATISTICS = {key: sport for sport, axes in radar.AXES.items() for key, *_ in axes}

READING_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "sport": {"type": ["string", "null"], "enum": ["football", "table_tennis", None]},
        "gender": {"type": ["string", "null"], "enum": ["male", "female", None]},
        "position_group": {"type": ["string", "null"], "enum": [*GROUPS, None]},
        "age_from": {"type": ["integer", "null"]},
        "age_to": {"type": ["integer", "null"]},
        "statistic": {"type": ["string", "null"], "enum": [*STATISTICS, None]},
        "players": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "intent", "sport", "gender", "position_group", "age_from", "age_to", "statistic",
        "players",
    ],
}

SYSTEM_PROMPT = """You read questions about players on a sports talent platform and fill in a JSON form. You never answer the question.

intent:
- "leaders": who is best at a statistic in a group ("top 5 strikers for goals", "best passers among 15 year olds").
- "player": how one named player is doing ("how good is Omar Hassan", "stats for Omar Hassan").
- "similar": players like one named player ("who plays like Omar Hassan").
- "compare": two or three named players against each other ("compare Omar Hassan and Ali Adel").
- "unsupported": anything else (injuries, salaries, transfers, predictions, opinions, news).

sport: "football" or "table_tennis" (table tennis, ping pong, تنس طاولة). null if not said, unless the statistic or position makes it clear.
gender: "male" for boys, men, he; "female" for girls, women, she (بنات, سيدات). null if not said.
position_group: goalkeeper; defender (CB, LB, RB, centre back, full back); midfielder (CDM, CM, CAM); forward (striker, winger, ST, LW, RW). null if not said. Table tennis has none.
age_from and age_to, whole years:
- "15 year olds" or "aged 15": 15 and 15.
- "under 16" or "U16": null and 15.
- "16 and over", "16+" or "aged 16 or older": 16 and null.
- "over 16" or "older than 16": 17 and null.
- "between 14 and 16": 14 and 16.
- "adults" or "seniors": 18 and null.
null when no age is said.
statistic, football: goals, shots, key_passes (chances created), assists, passes_attempted (passes, passing volume), pass_completion (passing accuracy), tackles (defending, winning the ball), distance_km (running, work rate, stamina).
statistic, table tennis: point_share (points won), set_share (sets won, winning), service_winners (serve), unforced_errors (mistakes, consistency).
"best passer" means pass_completion. "scorer" means goals. "creative" means key_passes. null if no statistic is asked for.
players: every person's name exactly as written in the question, in its own script. A position or a group ("a full back", "strikers", "مدافع") is not a name. Empty if none.
"""


# Worked examples, sent as earlier turns of the conversation. Written for this purpose: none
# is a question from eval/assistant_questions.json, so neither score is inflated by them.
EXAMPLES: list[tuple[str, dict]] = [
    ("which centre backs win the most tackles, under 17", {
        "intent": "leaders", "sport": "football", "gender": None, "position_group": "defender",
        "age_from": None, "age_to": 16, "statistic": "tackles", "players": []}),
    ("top goal scorers in the academy", {
        "intent": "leaders", "sport": "football", "gender": None, "position_group": None,
        "age_from": None, "age_to": None, "statistic": "goals", "players": []}),
    ("girls who make the fewest mistakes at table tennis", {
        "intent": "leaders", "sport": "table_tennis", "gender": "female", "position_group": None,
        "age_from": None, "age_to": None, "statistic": "unforced_errors", "players": []}),
    ("how is Tamer Fouad doing", {
        "intent": "player", "sport": None, "gender": None, "position_group": None,
        "age_from": None, "age_to": None, "statistic": None, "players": ["Tamer Fouad"]}),
    ("أحسن جناح في الأسيست", {
        "intent": "leaders", "sport": "football", "gender": None, "position_group": "forward",
        "age_from": None, "age_to": None, "statistic": "assists", "players": []}),
    ("لاعبين زي عمرو خالد", {
        "intent": "similar", "sport": None, "gender": None, "position_group": None,
        "age_from": None, "age_to": None, "statistic": None, "players": ["عمرو خالد"]}),
    ("Nour Samy or Adham Reda, who shoots more?", {
        "intent": "compare", "sport": None, "gender": None, "position_group": None,
        "age_from": None, "age_to": None, "statistic": "shots", "players": ["Nour Samy", "Adham Reda"]}),
    ("which midfielder should start next week", {
        "intent": "unsupported", "sport": None, "gender": None, "position_group": None,
        "age_from": None, "age_to": None, "statistic": None, "players": []}),
]


def _example_turns() -> list[dict]:
    turns = []
    for question, reading in EXAMPLES:
        turns.append({"role": "user", "content": question})
        turns.append({"role": "assistant", "content": json.dumps(reading, ensure_ascii=False)})
    return turns


@dataclass
class Reading:
    intent: str = "unsupported"
    sport: str | None = None
    gender: str | None = None
    position_group: str | None = None
    age_from: int | None = None
    age_to: int | None = None
    statistic: str | None = None
    players: list[str] = field(default_factory=list)


def ages_in(question: str) -> tuple[int | None, int | None] | None:
    """The age range a question names, by rule (app/ages.py), or None when it names none.

    Read by rule, not by the model: the model's commonest mistake on the development
    questions was "under 16" read as "aged 15"."""
    match = ages.find(question)
    return None if match is None else (match.age_from, match.age_to)


class OllamaUnavailable(Exception):
    """Ollama is not running, or the model is not pulled. Says which in its message."""


def _clean(raw: dict) -> Reading:
    """Keep only allowed values, then fill what the rest makes certain."""
    def pick(key, allowed):
        value = raw.get(key)
        return value if value in allowed else None

    def age(key):
        value = raw.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 60 else None

    reading = Reading(
        intent=raw.get("intent") if raw.get("intent") in INTENTS else "unsupported",
        sport=pick("sport", ("football", "table_tennis")),
        gender=pick("gender", ("male", "female")),
        position_group=pick("position_group", GROUPS),
        age_from=age("age_from"),
        age_to=age("age_to"),
        statistic=pick("statistic", STATISTICS),
        players=[p.strip() for p in raw.get("players") or [] if isinstance(p, str) and p.strip()],
    )
    # The intent has to agree with the names read. A small model often reads "most tackles by
    # a full back" as a comparison; with no names in it, it cannot be one. These are
    # consistency rules on the model's own reading, not a second guess at the question.
    named = len(reading.players)
    narrowed = (
        reading.statistic or reading.position_group or reading.sport or reading.gender
        or reading.age_from is not None or reading.age_to is not None
    )
    if reading.intent in ("player", "similar", "compare") and named == 0:
        reading.intent = "leaders" if narrowed else "unsupported"
    elif reading.intent == "compare" and named == 1:
        reading.intent = "player"
    elif reading.intent in ("player", "leaders") and named >= 2:
        reading.intent = "compare"
    # A statistic or a position belongs to one sport, so it settles an unsaid sport, and a
    # statistic from the other sport than the one said is dropped rather than guessed at.
    if reading.statistic and reading.sport is None:
        reading.sport = STATISTICS[reading.statistic]
    if reading.position_group and reading.sport is None:
        reading.sport = "football"
    if reading.statistic and STATISTICS[reading.statistic] != reading.sport:
        reading.statistic = None
    if reading.sport == "table_tennis":
        reading.position_group = None
    # A sport that registers one gender has nothing to choose. The model sometimes reads "girls"
    # into an Arabic question about football; the answer would then be an error, not players.
    module = sports.registry().get(reading.sport or "football")
    if module is not None and len(module.genders) == 1:
        reading.gender = None
    if (
        reading.age_from is not None and reading.age_to is not None
        and reading.age_from > reading.age_to
    ):
        reading.age_from, reading.age_to = reading.age_to, reading.age_from
    return reading


def read_question(question: str, *, model: str | None = None, url: str | None = None) -> Reading:
    """Ask the model to fill in the form for one question."""
    settings = get_settings()
    model = model or settings.ollama_assistant_model
    url = url or settings.ollama_url
    if not url:
        raise OllamaUnavailable("No language model is configured (OLLAMA_URL is unset).")
    body = json.dumps(
        {
            "model": model,
            "stream": False,
            "format": READING_SCHEMA,
            # Ollama unloads a model after five idle minutes, and loading it again takes most
            # of a minute on a laptop. An hour keeps the question box quick through a session.
            "keep_alive": "1h",
            "options": {"temperature": 0, "seed": 0, "num_predict": 200},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                *_example_turns(),
                {"role": "user", "content": question},
            ],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{url.rstrip('/')}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            reply = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise OllamaUnavailable(
                f"The model {model} is not pulled into Ollama. Run: "
                f"docker exec northstar-ollama ollama pull {model}"
            ) from exc
        raise OllamaUnavailable(f"Ollama answered with an error ({exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OllamaUnavailable(
            "The local language model is not running or did not answer. Start it with: "
            "docker compose -f docker/docker-compose.yml --profile llm up -d ollama"
        ) from exc
    text = (reply.get("message") or {}).get("content", "")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        log.warning("assistant reading was not JSON: %r", text[:200])
        raw = {}
    reading = _clean(raw if isinstance(raw, dict) else {})
    if (ages := ages_in(question)) is not None:
        reading.age_from, reading.age_to = ages
    return reading


# ---------------------------------------------------------------------------
# Answering, from the services the screens use
# ---------------------------------------------------------------------------

GROUP_WORDS = {
    "goalkeeper": "goalkeepers", "defender": "defenders", "midfielder": "midfielders",
    "forward": "forwards",
}
STAT_LABELS = {key: (label, unit) for axes in radar.AXES.values() for key, label, unit, _ in axes}
MAX_CANDIDATES = 8

CAN_DO = (
    "I can answer four kinds of question from the match records: who is best at a statistic "
    "in a group (\"top passers among 15 year old midfielders\"), how one player is doing "
    "(\"stats for Omar Hassan\"), who plays like a player (\"players like Omar Hassan\"), and "
    "how two or three players compare (\"compare Omar Hassan and Ali Adel\")."
)


def _ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return str(n) + {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _value(value: float, unit: str) -> str:
    return f"{value}%" if unit == "%" else f"{value} {unit}"


def chips(reading: Reading) -> list[str]:
    """The reading in words, for "How this was read"."""
    words = {
        "leaders": "best in a group", "player": "one player's statistics",
        "similar": "players like one player", "compare": "players compared",
        "unsupported": "not a question these records answer",
    }
    out = [words[reading.intent]]
    if reading.intent == "leaders":
        out.append((reading.sport or "football").replace("_", " "))
        if reading.gender:
            out.append({"male": "men and boys", "female": "women and girls"}[reading.gender])
        if reading.position_group:
            out.append(GROUP_WORDS[reading.position_group])
        if reading.age_from is not None or reading.age_to is not None:
            if reading.age_from == reading.age_to:
                out.append(f"aged {reading.age_from}")
            elif reading.age_to is None:
                out.append(f"aged {reading.age_from} and over")
            elif reading.age_from is None:
                out.append(f"aged {reading.age_to} and under")
            else:
                out.append(f"aged {reading.age_from} to {reading.age_to}")
    if reading.statistic and reading.intent in ("leaders", "player"):
        out.append(STAT_LABELS[reading.statistic][0].lower())
    if reading.intent != "leaders":
        out += [f"player: {name}" for name in reading.players]
    return out


def _role_label(sport: str | None) -> str:
    """What the sport module calls a player's role: a position in football, a style in table
    tennis."""
    module = sports.registry().get(sport or "football")
    return module.role_label if module is not None else "Role"


def _result(answer: str, *, columns=(), rows=(), link=None, note="") -> dict:
    return {
        "answer": answer, "columns": list(columns), "rows": list(rows), "link": link,
        "note": note,
    }


def _find(db: Session, caller: Caller, name: str) -> list[Player]:
    """Players the caller may open whose name matches, in Arabic or Latin spelling."""
    found = [
        p for p in db.execute(visible_players(caller)).scalars().unique()
        if names.matches(name, p.full_name, p.known_as)
    ]
    # A name typed in full and exactly is that player, even when other names sound alike.
    wanted = " ".join(name.split()).casefold()
    exact = [
        p for p in found
        if wanted in {" ".join((n or "").split()).casefold() for n in (p.full_name, p.known_as)}
    ]
    return [p for p in exact or found if may_view(db, caller, p)[0]]


def _one(db: Session, caller: Caller, name: str) -> tuple[Player | None, dict | None]:
    """The single player a name means, or a result that says why there is not one."""
    found = _find(db, caller, name)
    if len(found) == 1:
        return found[0], None
    if not found:
        return None, _result(
            f"No player you may open matches \"{name}\". Check the spelling, or find them on "
            "the search screen.",
            link={"label": "Search", "href": "/search"},
        )
    today = date.today()
    found.sort(key=lambda p: p.full_name)
    return None, _result(
        f"{len(found)} players you may open match \"{name}\". Which one did you mean?",
        columns=["Player", "Role", "Age"],
        rows=[
            {
                "player_id": str(p.id),
                "cells": [p.full_name, p.position or "", age_label(p.date_of_birth, today)],
            }
            for p in found[:MAX_CANDIDATES]
        ],
        note=f"Showing {MAX_CANDIDATES} of {len(found)}." if len(found) > MAX_CANDIDATES else "",
    )


def _explore_link(reading: Reading) -> dict:
    params: dict = {"view": "leaders", "sport": reading.sport or "football"}
    if reading.gender:
        params["gender"] = reading.gender
    params["group"] = reading.position_group or "all"
    if reading.age_from is not None:
        params["ageFrom"] = reading.age_from
    if reading.age_to is not None:
        params["ageTo"] = reading.age_to
    return {"label": "Open in Explore", "href": "/explore?" + urlencode(params)}


def _answer_leaders(db: Session, caller: Caller, reading: Reading) -> dict:
    try:
        body = explore.leaders(
            db, caller, sport=reading.sport, gender=reading.gender,
            group=reading.position_group, age_from=reading.age_from, age_to=reading.age_to,
            own_age=False,
        )
    except explore.ExploreError as error:
        return _result(str(error))
    link = _explore_link(reading)
    boards = {b["key"]: b for b in body["boards"]}

    if reading.statistic:
        board = boards.get(reading.statistic)
        label, unit = STAT_LABELS[reading.statistic]
        if board is None:
            return _result(
                f"{label} is not compared for goalkeepers: the records hold no goalkeeping "
                "statistics, so goalkeepers are compared on passing and distance only.",
                link=link,
            )
        if not board["leaders"]:
            reason = (
                "none of them are players you may open" if board["median"] is not None
                else "too few players have it on record, or they all have the same value. Try "
                "a wider age range or every position"
            )
            return _result(
                f"No leaders for {label.lower()} among {body['population']}: {reason}.",
                link=link, note=body["note"],
            )
        direction = "" if board["higher_is_better"] else " (lower is better)"
        return _result(
            f"Best for {label.lower()}{direction} among {body['population']}. "
            f"The median is {_value(board['median'], unit)}.",
            columns=["Player", _role_label(body["sport"]), "Age", label, "Percentile"],
            rows=[
                {
                    "player_id": str(leader["player_id"]),
                    "cells": [
                        leader["full_name"], leader["position"] or "", leader["age_label"],
                        _value(leader["value"], unit), _ordinal(leader["percentile"]),
                    ],
                }
                for leader in board["leaders"]
            ],
            link=link, note=body["note"],
        )

    rows = [
        {
            "player_id": str(board["leaders"][0]["player_id"]),
            "cells": [
                board["leaders"][0]["full_name"], board["label"],
                _value(board["leaders"][0]["value"], board["unit"]),
                _ordinal(board["leaders"][0]["percentile"]),
            ],
        }
        for board in body["boards"]
        if board["leaders"]
    ]
    if not rows:
        return _result(f"No leaders among {body['population']}.", link=link, note=body["note"])
    return _result(
        f"The best on each statistic among {body['population']}.",
        columns=["Player", "Statistic", "Value", "Percentile"], rows=rows, link=link,
        note=body["note"],
    )


def _answer_player(db: Session, caller: Caller, reading: Reading) -> dict:
    if not reading.players:
        return _result("Which player? Name them in the question.")
    player, problem = _one(db, caller, reading.players[0])
    if problem:
        return problem
    body = radar.player_radar(db, player)
    link = {"label": "Open profile", "href": f"/players/{player.id}"}
    if not body["axes"]:
        return _result(f"{player.full_name}: {body['note']}", link=link)
    # The statistic asked about first, then the rest as the radar orders them.
    axes = sorted(body["axes"], key=lambda a: a["key"] != reading.statistic)
    who = (
        f"{player.full_name} ({player.position or 'no ' + _role_label(player.primary_sport).lower()}, "
        f"{age_label(player.date_of_birth, date.today())})"
    )
    return _result(
        f"{who}, compared among {body['population']}.",
        columns=["Statistic", "Value", "Percentile"],
        rows=[
            {
                "player_id": None,
                "cells": [
                    a["label"], _value(a["value"], a["unit"]),
                    _ordinal(a["percentile"]) if a["percentile"] is not None
                    else "not enough players",
                ],
            }
            for a in axes
        ],
        link=link, note=body["note"],
    )


def _answer_similar(db: Session, caller: Caller, reading: Reading) -> dict:
    if not reading.players:
        return _result("Like which player? Name them in the question.")
    player, problem = _one(db, caller, reading.players[0])
    if problem:
        return problem
    body = similar.similar_players(db, caller, player)
    link = {"label": "Open profile", "href": f"/players/{player.id}"}
    if not body["items"]:
        return _result(f"No similar players for {player.full_name}. {body['note']}", link=link)
    return _result(
        f"Players whose match record is most like that of {player.full_name}, closest first.",
        columns=["Player", _role_label(player.primary_sport), "Age", "Most alike on"],
        rows=[
            {
                "player_id": str(item["player_id"]),
                "cells": [
                    item["full_name"], item["position"] or "", item["age_label"],
                    ", ".join(item["alike"]),
                ],
            }
            for item in body["items"]
        ],
        link=link, note=body["note"],
    )


def _answer_compare(db: Session, caller: Caller, reading: Reading) -> dict:
    asked = reading.players[:3]
    if len(asked) < 2:
        return _result("Compare whom? Name two or three players in the question.")
    players = []
    for name in asked:
        player, problem = _one(db, caller, name)
        if problem:
            return problem
        players.append(player)
    if len({p.primary_sport for p in players}) > 1:
        return _result("Those players play different sports, so their statistics do not compare.")
    radars = [radar.player_radar(db, p) for p in players]
    keys = [a["key"] for a in max(radars, key=lambda r: len(r["axes"]))["axes"]]
    by_player = [{a["key"]: a for a in r["axes"]} for r in radars]

    def cell(axes: dict, key: str) -> str:
        a = axes.get(key)
        if a is None:
            return "n/a"
        place = _ordinal(a["percentile"]) if a["percentile"] is not None else "no percentile"
        return f"{_value(a['value'], a['unit'])} ({place})"

    among = "; ".join(
        f"{p.full_name} among {r['population']}" if r["population"]
        else f"{p.full_name}: {r['note']}"
        for p, r in zip(players, radars)
    )
    return _result(
        "Each value with its percentile among comparable players. " + among + ".",
        columns=["Statistic", *(p.full_name for p in players)],
        rows=[
            {"player_id": None, "cells": [STAT_LABELS[k][0], *(cell(a, k) for a in by_player)]}
            for k in keys
        ],
        link={
            "label": "Open in Compare",
            "href": "/compare?players=" + ",".join(str(p.id) for p in players),
        },
        note=(
            "Each player is placed among players like them, so two percentiles can come from "
            "different groups."
        ),
    )


_ANSWERS = {
    "leaders": _answer_leaders,
    "player": _answer_player,
    "similar": _answer_similar,
    "compare": _answer_compare,
}


def answer(db: Session, caller: Caller, question: str) -> dict:
    """Read the question, run it as the caller, and say what was read and what was found."""
    reading = read_question(question)
    handler = _ANSWERS.get(reading.intent)
    result = handler(db, caller, reading) if handler else _result(CAN_DO)
    return {
        "question": question,
        "reading": dict(reading.__dict__),
        "chips": chips(reading),
        "model": get_settings().ollama_assistant_model,
        **result,
    }
