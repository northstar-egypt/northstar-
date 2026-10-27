"""Is the stack ready to give the demo? Run this before presenting (docs/demo.md).

    python tests/e2e/demo_check.py

It checks every thing the demo script relies on, says which demo player to use, and warms the
two local models and the slow summary so nothing is cold in front of an audience. It changes
nothing in the database: the detector run is a dry run, rolled back.

Exit code 0 means ready. Each failure says how to fix it.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("E2E_API_URL", "http://localhost:8000")
WEB = os.environ.get("E2E_WEB_URL", "http://localhost:3000")
OLLAMA = os.environ.get("OLLAMA_HOST_URL", "http://localhost:11434")
REPO = Path(__file__).resolve().parents[2]

# Seeded youth footballers at academies other than the demo coach's, with long histories and
# no flags yet. The demo registers one of them a second time under his first and family
# names. Rehearsing uses one up (the second entry stays in the database), so the
# check names the first not yet used. tests/e2e uses a different player, so the suite never
# uses these up.
DEMO_PLAYERS = [  # (full name, what the coach types, date of birth, position)
    ("منير عصام فارس حجازي", "منير حجازي", "2010-06-09", "ST"),
    ("إسلام هشام لطفي", "إسلام لطفي", "2011-11-16", "ST"),
    ("هشام أحمد سعد شلبي", "هشام شلبي", "2012-08-13", "LW"),
]
MODELS = ("qwen2.5:3b", "qwen2.5:7b")

failures = 0


def report(ok: bool | None, what: str, fix: str = "") -> None:
    """ok True, False, or None for a warning that does not stop the demo."""
    global failures
    mark = {True: "ok  ", False: "FAIL", None: "warn"}[ok]
    print(f"[{mark}] {what}")
    if fix and ok is not True:
        print(f"       {fix}")
    failures += ok is False


def get(url: str, opener=None, timeout: float = 10):
    with (opener or urllib.request.build_opener()).open(url, timeout=timeout) as response:
        return json.load(response)


def post(url: str, body: dict, opener, timeout: float = 30):
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(request, timeout=timeout) as response:
        return json.load(response)


def signed_in(email: str, password: str):
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    post(f"{API}/auth/login", {"email": email, "password": password}, opener)
    return opener


def main() -> int:
    up = "docker compose -f docker/docker-compose.yml -f docker/docker-compose.gpu.yml --profile llm up -d"

    # 1. The services.
    try:
        get(f"{API}/health/db")
        report(True, f"API and database answer at {API}")
    except (urllib.error.URLError, OSError):
        report(False, f"no API or database at {API}", f"start the stack: {up}")
        return 1
    try:
        urllib.request.urlopen(f"{WEB}/login", timeout=60).close()
        report(True, f"web app answers at {WEB} (and has compiled the login page)")
    except (urllib.error.URLError, OSError):
        report(False, f"no web app at {WEB}", f"start the stack: {up}")

    # 2. The three accounts the script signs in as.
    identities = {row["role"]: row for row in get(f"{API}/dev/identities")}
    for role in ("coach", "scout", "federation"):
        row = identities.get(role)
        report(row is not None, f"{role} account: {row['email'] if row else 'missing'}",
               "the dataset is not loaded; see README, Running locally")
    if failures:
        return 1
    coach = identities["coach"]
    print(f"       the coach's academy is {coach['organizationName']}")
    scout = signed_in(identities["scout"]["email"], identities["scout"]["demoPassword"])

    # Leftovers from the browser tests, which add players to this coach's academy on every run
    # (named "E2E ...", and second entries of the test flow's player). They fill the squad and
    # the integrity queue an audience would see.
    squad = get(f"{API}/players", signed_in(coach["email"], coach["demoPassword"]))
    leftovers = [r for r in squad if r["player"]["fullName"].startswith("E2E ")
                 or r["player"]["fullName"] == "مروان فؤاد"]
    report(None if leftovers else True,
           f"{len(leftovers)} test players in the coach's squad of {len(squad)}"
           if leftovers else f"no test players in the coach's squad ({len(squad)} players)",
           "reset the data before presenting (docs/demo.md, After a rehearsal)")

    # 3. Which demo player: the first whose second entry has not been made yet.
    chosen = None
    for full, typed, born, position in DEMO_PLAYERS:
        found = post(f"{API}/search", {"query": typed, "limit": 20}, scout)["results"]
        names = [r["player"]["fullName"] for r in found]
        original = next((r["player"] for r in found if r["player"]["fullName"] == full), None)
        if original is None or original.get("dateOfBirth") != born:
            report(None, f"{full} is not in this database as seeded")
            continue
        if names.count(full) != 1 or len(found) != 1:
            report(None, f"{full}: already registered a second time (a rehearsal); skipping")
            continue
        chosen = (full, typed, born, position, original)
        break
    if chosen is None:
        report(False, "every demo player has been used up by rehearsals",
               "reset the data: docker compose -f docker/docker-compose.yml down -v, then up")
        return 1
    full, typed, born, position, original = chosen
    # A height just above his last reading, so the merged growth chart does not show him
    # shrinking, and the form does not question it as unusual.
    last = get(f"{API}/players/{original['id']}/profile", scout)["latest"]["heightCm"]
    height = round(last + 1) if last else 160
    report(True, f"demo player: {full}, born {born}, {position}, last measured {last} cm")
    print(f"       the coach types: name {typed}, born {born}, position {position}, height {height}")

    # 4. The detector run, dry: it must read the database and write without error.
    done = subprocess.run(
        [sys.executable, "-m", "ml.write_flags", "--from-database", "--dry-run"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    report(done.returncode == 0, "detector run works (dry run, nothing written)",
           (done.stderr or done.stdout).strip()[-400:])

    # 5. The local models: present, then warmed by real requests.
    try:
        tags = {m["name"] for m in get(f"{OLLAMA}/api/tags")["models"]}
        for model in MODELS:
            report(model in tags, f"model {model} downloaded",
                   f"docker exec northstar-ollama ollama pull {model}")
    except (urllib.error.URLError, OSError):
        report(None, f"no Ollama at {OLLAMA}: Ask and the written summary will say the model is "
               "not running", f"start the stack with --profile llm: {up}")
        tags = set()

    if tags:
        started = time.monotonic()
        try:
            answer = post(f"{API}/assistant", {"question": "strikers under 16"}, scout, timeout=120)
            seconds = time.monotonic() - started
            report(bool(answer.get("answer")),
                   f"Ask answered in {seconds:.0f} s (warm is 2 to 3 s)")
        except (urllib.error.URLError, OSError) as exc:
            report(None, f"Ask did not answer: {exc}")

        # The summary is the slow one (about 80 s cold). Written once for the original's
        # profile as the scout sees it, it is then served from the cache during the demo.
        started = time.monotonic()
        try:
            written = get(f"{API}/players/{original['id']}/summary", scout, timeout=400)
            seconds = time.monotonic() - started
            report(written.get("summary") is not None,
                   f"summary for {full} ready ({seconds:.0f} s)", written.get("note", ""))
        except (urllib.error.URLError, OSError) as exc:
            report(None, f"summary did not finish: {exc}")

    print()
    print("ready" if not failures else f"{failures} problem(s) above; fix them before presenting")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
