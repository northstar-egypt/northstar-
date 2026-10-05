"""The short written summary at the top of the player profile, from a local Ollama model.

The model writes sentences. It does not decide what is true. The design keeps those apart:

1. **Facts first.** `facts()` turns the profile the caller is already allowed to see into a
   short list of plain statements, with every number written the way the screen shows it.
   It is built from the output of `views.build_profile`, after the role and consent filters,
   so the model is never told anything the caller could not read on the page. A scout who
   may not see flags gets a fact sheet with no flags in it. The player's name is left out:
   the page already shows it, and an Arabic name is the one thing a small model is likely
   to spell wrongly.
2. **The model rephrases.** `qwen2.5:3b` by default (`OLLAMA_MODEL`), temperature 0, asked
   for two to four sentences built only from the facts.
3. **Every number is checked.** `unsupported()` pulls each number out of the reply, digits
   and number words alike, and accepts it only if it is a number on the fact sheet, or that
   number rounded to fewer decimals. A reply that also names a flag the fact sheet does not
   hold is refused the same way. One unsupported number and the whole summary is withheld,
   because a summary that is right except for one invented figure is the failure this
   project exists not to ship.

What the check cannot catch: a wrong sentence with no number in it ("he is a fast player").
The prompt forbids opinions and the screen labels the text as generated, but that part rests
on the model and the label, not on code. The evaluation in the PR that added this reports how
often the check fired on the synthetic players.

When there is no summary the endpoint says why (Ollama not running, model not pulled,
reply withheld), and the profile renders without it. Results are cached per fact sheet, so a
profile is written once until its numbers change.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date

from app.config import get_settings
from app.services.flags import FLAG_LABELS

log = logging.getLogger(__name__)

# A generous ceiling: a 3B model on a laptop CPU takes 5 to 20 seconds for a summary.
_TIMEOUT_SECONDS = 90
_CACHE_SIZE = 512

_MONTHS = (
    "January February March April May June July August September October November December"
).split()

# Number words a summary might use instead of digits. Checked like digits.
_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "twenty": 20,
    "once": 1, "twice": 2,
}
_NUMBER = re.compile(r"(?<![\w.])-?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)")
_WORD = re.compile(r"\b(" + "|".join(_WORDS) + r")\b", re.IGNORECASE)

# What the reply may not mention unless the fact sheet does: every kind of flag, so a model
# cannot tell a caller without flag access that a flag exists.
_FLAG_TERMS = {
    "late_bloomer": ("late bloomer", "late-bloomer", "late developer", "late maturing"),
    "fraud": ("fraud", "misrepresent", "falsif"),
    "duplicate": ("duplicate",),
    "anomaly": ("anomal",),
    "breakout": ("breakout", "break out", "breaking out"),
}

SYSTEM_PROMPT = """You write a short summary of a young athlete's record for a coach.

Rules:
- Use only the facts you are given. Do not add any fact, number, comparison or date.
- Copy every number exactly as it is written in the facts, with its unit.
- Write two to four plain sentences in English. No lists, no headings.
- Refer to the athlete as "the player". Do not use a name.
- Do not judge talent, potential or character, and do not give advice.
- If the facts say something is not known, you may say it is not known. Do not guess it.
- Do not mention anything that is not in the facts."""


@dataclass(frozen=True)
class Summary:
    text: str | None
    # Why there is no text, or where the text came from. Shown on the profile either way.
    note: str
    model: str | None = None


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


def _month(d: date | str | None) -> str | None:
    if d is None:
        return None
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{_MONTHS[d.month - 1]} {d.year}"


def _num(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def _age(label: str) -> str:
    """'17y 3m' as words, so the numbers in it read the same as in a sentence."""
    match = re.fullmatch(r"(\d+)y (\d+)m", label or "")
    if not match:
        return label
    years, months = match.groups()
    return f"{years} years {months} months"


def facts(profile: dict) -> list[str]:
    """The profile as plain statements, numbers formatted the way the screen shows them.

    Takes the dict `views.build_profile` returns, which is already filtered for the caller.
    """
    player = profile["player"]
    lines: list[str] = []

    gender = {"male": "boy", "female": "girl"}.get(getattr(player, "sex", None) or "", None)
    sport = (getattr(player, "primary_sport", None) or "").replace("_", " ")
    position = getattr(player, "position", None)
    who = f"A {gender}" if gender else "A player"
    lines.append(
        f"{who} aged {_age(profile['age_label'])}"
        + (f", playing {sport}" if sport else "")
        + (f" as {position}" if position else "")
        + "."
    )

    latest = profile.get("latest") or {}
    if latest.get("heightCm") is not None:
        lines.append(f"Latest height: {_num(latest['heightCm'], 1)} cm.")
    if latest.get("weightKg") is not None:
        lines.append(f"Latest weight: {_num(latest['weightKg'], 1)} kg.")

    growth = profile.get("growth") or {}
    measured = growth.get("measured") or []
    if measured:
        lines.append(
            f"Height has been measured {len(measured)} times, from {_month(measured[0]['date'])} "
            f"to {_month(measured[-1]['date'])}."
        )
    forecast_points = growth.get("forecast") or []
    if forecast_points:
        last = forecast_points[-1]
        lines.append(
            f"Height forecast for {_month(last['date'])}: {_num(last['value'], 1)} cm, with an "
            f"80% range of {_num(last['lower'], 1)} to {_num(last['upper'], 1)} cm."
        )
    else:
        note = growth.get("forecast_note")
        lines.append("There is no height forecast." + (f" Reason: {note}" if note else ""))

    if profile.get("maturity") is None:
        lines.append("Biological maturity is not estimated.")

    for pc in profile.get("percentiles") or []:
        decimals = 2 if pc["unit"] == "s" or pc["value"] < 10 else 0
        better = "higher is better" if pc["higher_is_better"] else "lower is better"
        lines.append(
            f"{pc['label']}: {_num(pc['value'], decimals)} {pc['unit']}, percentile "
            f"{pc['percentile']} against {pc['population']} ({better})."
        )

    for section in profile.get("performance") or []:
        stats = [
            f"{s['label'].lower()} {round(s['value'] * 100)}%"
            if s["format"] == "percent"
            else f"{s['label'].lower()} {_num(s['value'], 2)}"
            for s in section.get("summary") or []
        ]
        count = len(section.get("entries") or [])
        line = f"{section['label']}: {count} records"
        if stats:
            line += ", " + ", ".join(stats)
        lines.append(line + ".")

    flags = profile.get("flags") or []
    if flags:
        labels = ", ".join(f["label"] for f in flags)
        lines.append(f"Open flags: {labels}.")
        if profile.get("flag_reason"):
            lines.append(f"Flag reason: {profile['flag_reason']}")

    return lines


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


def _numbers(text: str) -> list[str]:
    found = [m.group(1).replace(",", "") for m in _NUMBER.finditer(text)]
    found += [str(_WORDS[m.group(1).lower()]) for m in _WORD.finditer(text)]
    return found


def _decimals(number: str) -> int:
    return len(number.split(".")[1]) if "." in number else 0


def _supported(number: str, allowed: list[tuple[float, int]]) -> bool:
    """True when `number` is on the fact sheet, or a fact rounded to fewer decimals."""
    value, decimals = abs(float(number)), _decimals(number)
    return any(
        value == fact or (decimals < fact_decimals and round(fact, decimals) == value)
        for fact, fact_decimals in allowed
    )


def unsupported(text: str, lines: list[str]) -> list[str]:
    """Everything in `text` the fact sheet does not back: numbers, and flags it does not hold.

    An empty list means the text may be shown.
    """
    sheet = "\n".join(lines)
    allowed = [(abs(float(n)), _decimals(n)) for n in _numbers(sheet)]
    problems = [n for n in _numbers(text) if not _supported(n, allowed)]

    lowered, sheet_lowered = text.lower(), sheet.lower()
    for flag_type, terms in _FLAG_TERMS.items():
        label = FLAG_LABELS.get(flag_type, flag_type).lower()
        on_sheet = label in sheet_lowered or any(t in sheet_lowered for t in terms)
        if not on_sheet and any(t in lowered for t in terms):
            problems.append(f"flag: {flag_type}")
    return problems


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


class OllamaUnavailable(Exception):
    """Ollama is not running, or the model is not pulled. Says which in its message."""


def ask_ollama(lines: list[str], *, model: str, url: str) -> str:
    """One chat call to Ollama. Standard library only, so the API gains no dependency."""
    body = json.dumps(
        {
            "model": model,
            "stream": False,
            "options": {"temperature": 0, "seed": 0, "num_predict": 220},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "Facts:\n" + "\n".join(f"- {l}" for l in lines)},
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
            "The local language model is not running. Start it with: "
            "docker compose -f docker/docker-compose.yml --profile llm up -d ollama"
        ) from exc
    return (reply.get("message") or {}).get("content", "").strip()


_cache: OrderedDict[str, Summary] = OrderedDict()
_lock = threading.Lock()


def summarise(profile: dict) -> Summary:
    """The summary for a profile, or no summary and the reason."""
    settings = get_settings()
    model, url = settings.ollama_model, settings.ollama_url
    if not url:
        return Summary(None, "No language model is configured (OLLAMA_URL is unset).")

    lines = facts(profile)
    key = hashlib.sha256(("\n".join([model, *lines])).encode("utf-8")).hexdigest()
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

    try:
        text = ask_ollama(lines, model=model, url=url)
    except OllamaUnavailable as exc:
        # Not cached: the next request should try again once Ollama is up.
        return Summary(None, str(exc))

    problems = unsupported(text, lines) if text else ["empty reply"]
    if problems:
        log.warning("summary withheld for unsupported content: %s", problems)
        result = Summary(
            None,
            "A summary was generated but not shown: it contained something that is not on "
            "this page (" + ", ".join(problems[:5]) + ").",
            model,
        )
    else:
        result = Summary(
            text,
            f"Written by a local model ({model}) from the numbers on this page. Every number "
            "in it was checked against them. Not a scouting opinion.",
            model,
        )

    with _lock:
        _cache[key] = result
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return result


def clear_cache() -> None:
    with _lock:
        _cache.clear()
