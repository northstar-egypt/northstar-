"""How often the assistant reads a question right. Needs Ollama running; no database.

    cd apps/api
    python -m eval.run_assistant_eval --split dev
    python -m eval.run_assistant_eval --split test --model qwen2.5:3b

A reading is right when everything that changes the answer is right: the intent, and for
that intent the fields in the question's `expect`. Both sides are compared after the defaults
the assistant itself applies (no sport means football, football means male), so a reading is
not marked wrong for saying what would have been assumed anyway. Names are compared ignoring
case, spacing and order.

The prompt is written against `dev`. `test` is held out: run it to report, never to tune.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.services import assistant

QUESTIONS = Path(__file__).with_name("assistant_questions.json")


def _effective(field: str, value, reading: dict):
    sport = reading.get("sport") or "football"
    if field == "sport":
        return value or "football"
    if field == "gender" and sport == "football":
        return "male"
    if field == "players":
        return sorted(" ".join(p.lower().split()) for p in value or [])
    return value


def score(expect: dict, got: dict) -> list[str]:
    """The fields that were read wrong; empty when the reading is right."""
    if got["intent"] != expect["intent"]:
        return ["intent"]
    wrong = []
    for field, want in expect.items():
        if field == "intent":
            continue
        if _effective(field, want, expect) != _effective(field, got.get(field), got):
            wrong.append(field)
    return wrong


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--model", default=None)
    parser.add_argument("--url", default="http://localhost:11434")
    args = parser.parse_args()

    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))[args.split]
    # One untimed call first, so loading the model from disk is not counted against question 1.
    assistant.read_question("warm up", model=args.model, url=args.url)
    right, by_field, seconds = 0, {}, []
    for item in questions:
        started = time.monotonic()
        reading = assistant.read_question(item["q"], model=args.model, url=args.url).__dict__
        seconds.append(time.monotonic() - started)
        wrong = score(item["expect"], reading)
        right += not wrong
        for field in wrong:
            by_field[field] = by_field.get(field, 0) + 1
        if wrong:
            shown = {k: reading[k] for k in ("intent", *item["expect"]) if k in reading}
            print(f"WRONG {wrong}: {item['q']}\n      got {shown}")

    seconds.sort()
    print(
        f"\n{args.split}, {args.model or 'default model'}: {right} of {len(questions)} read right "
        f"({right / len(questions):.0%}). Wrong by field: {by_field or 'none'}. "
        f"Seconds per question: median {seconds[len(seconds) // 2]:.1f}, slowest {seconds[-1]:.1f}."
    )


if __name__ == "__main__":
    main()
