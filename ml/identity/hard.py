"""Harder duplicates than the generator plants, for grading the identity engine.

The generator's duplicates are easy (ml/README.md says so): the same Arabic name with a spelling
difference, a date of birth a few days off, always the same sex and sport. A national register
also meets the same person:

- **in Latin script**, as a professional or European source spells them (Mohamed, Mohammed,
  Muhammad...), while the academy wrote Arabic;
- **with no date of birth**, as StatsBomb's records have none;
- **at another club**, registered by a different organisation.

This module takes a generated dataset and turns some of its planted duplicates into those,
leaving the answer key as it is. So that none of these is a give-away, the same happens to
ordinary players too: some are spelled in Latin and some lose their date of birth, though they
have no twin. The generator itself is untouched, so no published number can move.

Latin spellings come from apps/api/tests/name_spellings.py: real-world spellings of every name
the generator uses. Only the held-out half and the fresh set are used: the name matcher's rules
(app/names.py) were written looking at the other half, which would flatter it here.
"""

from __future__ import annotations

import copy
import random
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parents[2] / "apps" / "api"
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from app import names  # noqa: E402
from tests.name_spellings import SPELLINGS, half  # noqa: E402
from tests.name_spellings_fresh import FRESH  # noqa: E402

# Shares of duplicate clones changed, each independently.
CLONE_LATIN = 0.5
CLONE_NO_DOB = 0.4
CLONE_OTHER_CLUB = 0.4
# Shares of ordinary players changed the same way, so neither is a give-away.
OTHER_LATIN = 0.15
OTHER_NO_DOB = 0.1


def _spelling_table() -> dict[str, list[str]]:
    table: dict[str, list[str]] = {}
    for arabic, spellings in SPELLINGS.items():
        if half(arabic) == "held out":
            table.setdefault(names._normalise_arabic(arabic), []).extend(spellings)
    for arabic, spellings in FRESH.items():
        table.setdefault(names._normalise_arabic(arabic), []).extend(spellings)
    return table


TABLE = _spelling_table()


def latin(name: str, rng: random.Random) -> str | None:
    """A Latin spelling of an Arabic name, word by word; None when a word has no spelling in the
    table (the name is then left in Arabic)."""
    out = []
    for word in names._arabic_words(name):
        options = TABLE.get(names._normalise_arabic(word))
        if not options:
            return None
        out.append(rng.choice(options))
    return " ".join(out) if out else None


def harden(tables: dict[str, list[dict]], truth: dict, seed: int) -> tuple[dict[str, list[dict]], dict, dict]:
    """A copy of `tables` with the changes above, a count of what was changed, and for each clone
    the changes it got ("latin", "no_dob", "other_club")."""
    rng = random.Random(f"hard-{seed}")
    tables = copy.deepcopy(tables)
    players = {p["id"]: p for p in tables["players"]}
    clones = {pid for c in truth["cases"]["duplicates"] for pid in c["player_ids"] if pid != c["canonical_player_id"]}
    in_clusters = {pid for c in truth["cases"]["duplicates"] for pid in c["player_ids"]}
    orgs = [o for o in tables.get("organizations", []) if o.get("type") in ("club", "academy")]
    counts = {"clone_latin": 0, "clone_no_dob": 0, "clone_other_club": 0, "other_latin": 0, "other_no_dob": 0,
              "clones": len(clones)}
    changed: dict[str, list[str]] = {pid: [] for pid in clones}
    for pid, p in sorted(players.items()):
        if pid in clones:
            if rng.random() < CLONE_LATIN and (spelled := latin(p["full_name"], rng)):
                p["full_name"] = spelled
                counts["clone_latin"] += 1
                changed[pid].append("latin")
            if rng.random() < CLONE_NO_DOB:
                p["date_of_birth"] = None
                counts["clone_no_dob"] += 1
                changed[pid].append("no_dob")
            if rng.random() < CLONE_OTHER_CLUB and orgs:
                for a in tables["affiliations"]:
                    if a["player_id"] == pid:
                        a["organization_id"] = rng.choice(orgs)["id"]
                counts["clone_other_club"] += 1
                changed[pid].append("other_club")
        elif pid not in in_clusters:
            if rng.random() < OTHER_LATIN and (spelled := latin(p["full_name"], rng)):
                p["full_name"] = spelled
                counts["other_latin"] += 1
            if rng.random() < OTHER_NO_DOB:
                p["date_of_birth"] = None
                counts["other_no_dob"] += 1
    return tables, counts, changed
