"""Grading the diaspora submission checks (decision 0011) on planted submissions.

The checks that need grading are the two built on the identity engine
(ml/identity/submissions.py, the code the API runs): **likely the same person on record**, and
**the same name with a different date of birth** (possible age misrepresentation). Validation
is deterministic and is tested, not graded; so is the numbers check.

The register is a generated dataset (data/pipelines/synthetic), its players with their clubs,
the same as the identity engine's evaluation (ml/run_identity_eval.py). Four kinds of
submission are planted into it, each with a known answer:

- **on record**: a player on record, submitted again from a club abroad. Spelled in Latin
  letters half the time (ml/identity/hard.py: the held-out real-world spellings, which the
  name matcher's rules were not written from); the date of birth exact, a typing slip of 1 to
  6 days, or day and month swapped. Right answer: "likely the same person" names them.
- **age fraud**: a player on record submitted with a later date of birth, 1 to 36 months
  younger on paper, spelled as above. Right answer: "same name, different date of birth"
  names them.
- **namesake**: a different person with exactly the same full name as a player on record,
  born 1 to 10 years apart. Right answer: neither check names that player. Within
  FRAUD_YEARS the date check names them anyway, by design (it cannot tell a namesake from a
  fraud); this measures how often that happens.
- **sibling**: a player's family name with another given name, born the same day (twins) or 9
  to 30 months apart. Right answer: neither check names that player.
- **new**: someone not on record, a given name and family words drawn from the register's own
  names and recombined so the full name is nobody's on record, born on a random day in the
  register's range. Right answer: neither check raises anything.

Nothing here is tuned. The link threshold is the engine's (chosen on the calibration seeds for
the engine itself); the week that separates a typing slip from a different date is the
engine's too. The calibration seeds 101, 202 and 303 were run while building this; the
reported numbers are on other seeds.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from ml.identity import engine, hard
from ml.identity import submissions as matching

REPORTED = [20260827, 7, 99, 404, 555]
CALIBRATION = [101, 202, 303]
# Players in each generated register: nearer a real one than the generator's default of 200.
PLAYERS = 1000
PLANTS = {"on_record": 60, "age_fraud": 40, "sibling": 30, "namesake": 30, "new": 100}
# What the API shows the reviewer: the strongest few of each list.
SHOWN = 5


@dataclass
class Plant:
    kind: str
    record: engine.Record
    # The player the submission is (on record, age fraud) or is not (sibling); None for new.
    target: str | None
    detail: dict


def _words(name: str) -> list[str]:
    return name.split()


def _spelled(name: str, rng: random.Random, latin_share: float = 0.5) -> tuple[str, bool]:
    if rng.random() < latin_share and (spelled := hard.latin(name, rng)):
        return spelled, True
    return name, False


def _swap(d: date) -> date | None:
    if d.day <= 12 and d.day != d.month:
        try:
            return date(d.year, d.day, d.month)
        except ValueError:
            return None
    return None


def _record(pid: str, name: str, source: dict, dob: date, rng: random.Random) -> engine.Record:
    nationality = set(source.get("nationality") or [])
    if rng.random() < 0.5:
        nationality.add(rng.choice(["DE", "FR", "NL", "BE", "SE", "US", "GB", "IT"]))
    return engine.Record(id=pid, names=[name], sex=source.get("sex"), sport=source.get("primary_sport"),
                         date_of_birth=dob, nationality=frozenset(nationality),
                         clubs=frozenset([f"Club abroad {rng.randint(1, 500)}"]), source="submission")


def plant(tables: dict, seed: int, counts: dict[str, int] = PLANTS) -> list[Plant]:
    rng = random.Random(f"submissions-{seed}")
    players = [p for p in tables["players"] if p.get("date_of_birth") and p.get("full_name")]
    dob = {p["id"]: date.fromisoformat(p["date_of_birth"]) if isinstance(p["date_of_birth"], str)
           else p["date_of_birth"] for p in players}
    taken = {" ".join(_words(p["full_name"])) for p in tables["players"] if p.get("full_name")}
    givens = sorted({_words(p["full_name"])[0] for p in players if len(_words(p["full_name"])) >= 2})
    rests = sorted({w for p in players for w in _words(p["full_name"])[1:]})
    low, high = min(dob.values()), max(dob.values())
    out: list[Plant] = []

    for i in range(counts["on_record"]):
        p = rng.choice(players)
        name, latin = _spelled(p["full_name"], rng)
        roll, born = rng.random(), dob[p["id"]]
        when = "exact"
        if roll < 0.15:
            born, when = born + timedelta(days=rng.choice([-1, 1]) * rng.randint(1, 6)), "typing slip"
        elif roll < 0.30 and (swapped := _swap(born)):
            born, when = swapped, "day and month swapped"
        out.append(Plant("on_record", _record(f"plant:on_record:{i}", name, p, born, rng), p["id"],
                         {"latin": latin, "dob": when}))

    for i in range(counts["age_fraud"]):
        p = rng.choice(players)
        name, latin = _spelled(p["full_name"], rng)
        months = rng.randint(1, 36)
        born = dob[p["id"]] + timedelta(days=round(months * 30.44))
        out.append(Plant("age_fraud", _record(f"plant:age_fraud:{i}", name, p, born, rng), p["id"],
                         {"latin": latin, "months": months}))

    for i in range(counts["sibling"]):
        p = rng.choice([q for q in players if len(_words(q["full_name"])) >= 2])
        words = _words(p["full_name"])
        given = rng.choice([g for g in givens if engine.word_key(g) != engine.word_key(words[0])])
        twin = rng.random() < 0.3
        born = dob[p["id"]] if twin else dob[p["id"]] + timedelta(days=rng.choice([-1, 1]) * rng.randint(270, 913))
        name, latin = _spelled(" ".join([given, *words[1:]]), rng)
        out.append(Plant("sibling", _record(f"plant:sibling:{i}", name, p, born, rng), p["id"],
                         {"latin": latin, "twin": twin}))

    for i in range(counts["namesake"]):
        p = rng.choice(players)
        name, latin = _spelled(p["full_name"], rng)
        years = rng.randint(1, 10)
        born = dob[p["id"]] + timedelta(days=rng.choice([-1, 1]) * (round(years * 365.25) + rng.randint(-60, 60)))
        out.append(Plant("namesake", _record(f"plant:namesake:{i}", name, p, born, rng), p["id"],
                         {"latin": latin, "years": years}))

    made = 0
    while made < counts["new"]:
        name = " ".join([rng.choice(givens), *rng.sample(rests, rng.choice([2, 3]))])
        if name in taken:
            continue
        source = rng.choice(players)
        born = low + timedelta(days=rng.randint(0, (high - low).days))
        spelled, latin = _spelled(name, rng)
        out.append(Plant("new", _record(f"plant:new:{made}", spelled, source, born, rng), None, {"latin": latin}))
        made += 1
    return out


def _person(truth: dict) -> dict[str, set[str]]:
    """Every record of the same person, by record: the generator's planted duplicates."""
    out: dict[str, set[str]] = {}
    for case in truth["cases"]["duplicates"]:
        group = set(case["player_ids"])
        for pid in group:
            out[pid] = group
    return out


def judge(plant_: Plant, records: dict[str, engine.Record], fitted: matching.Fitted) -> dict:
    """What each check showed the reviewer for one plant, as the API shows it."""
    likely, twins = matching.classify(matching.score_one(plant_.record, records, fitted))
    shown = likely[:SHOWN]
    dob_raised = [p for p in shown if p.levels.get("dob") == "conflict"] + twins[:SHOWN]
    return {"likely": [p.b for p in shown], "dob": [p.b for p in dob_raised]}


def evaluate_seed(seed: int, players: int | None = PLAYERS) -> dict:
    from ml.run_identity_eval import _dataset

    tables, truth = _dataset(seed, players)
    records = {r.id: r for r in engine.records_from_tables(tables)}
    fitted = matching.fit(list(records.values()))
    person = _person(truth)
    rows = []
    for p in plant(tables, seed):
        seen = judge(p, records, fitted)
        same = person.get(p.target, {p.target}) if p.target else set()
        rows.append({
            "kind": p.kind, **p.detail,
            "likely_raised": bool(seen["likely"]),
            "likely_right": bool(same & set(seen["likely"])),
            "dob_raised": bool(seen["dob"]),
            "dob_right": bool(same & set(seen["dob"])),
        })
    return {"seed": seed, "players": len(records), "rows": rows}


def _share(hits: int, of: int) -> str:
    return f"{hits}/{of} ({100 * hits / of:.0f}%)" if of else "n/a"


def summarise(results: list[dict]) -> dict:
    rows = [r for res in results for r in res["rows"]]
    by = {k: [r for r in rows if r["kind"] == k] for k in PLANTS}
    on_record = by["on_record"] + by["age_fraud"]

    def prf(tp: int, raised: int, positives: int) -> dict:
        precision = tp / raised if raised else None
        recall = tp / positives if positives else None
        f1 = 2 * precision * recall / (precision + recall) if precision and recall else 0.0
        return {"tp": tp, "raised": raised, "positives": positives, "precision": precision, "recall": recall, "f1": f1}

    likely = prf(sum(r["likely_right"] for r in by["on_record"]),
                 sum(r["likely_raised"] for r in by["on_record"] + by["sibling"] + by["namesake"] + by["new"]),
                 len(by["on_record"]))
    # A "likely" raised on an age-fraud plant that names the right person is not a false alarm.
    likely["raised_on_age_fraud"] = sum(r["likely_raised"] for r in by["age_fraud"])
    dob = prf(sum(r["dob_right"] for r in by["age_fraud"]),
              sum(r["dob_raised"] for r in rows),
              len(by["age_fraud"]))
    either = sum((r["likely_right"] or r["dob_right"]) for r in on_record)
    return {
        "seeds": [res["seed"] for res in results],
        "players": [res["players"] for res in results],
        "counts": {k: len(v) for k, v in by.items()},
        "likely": likely,
        "dob": dob,
        "either_on_record": (either, len(on_record)),
        "false_alarm_new": (sum((r["likely_raised"] or r["dob_raised"]) for r in by["new"]), len(by["new"])),
        "sibling_named": (sum((r["likely_right"] or r["dob_right"]) for r in by["sibling"]), len(by["sibling"])),
        "twin_named": (sum((r["likely_right"] or r["dob_right"]) for r in by["sibling"] if r["twin"]),
                       sum(1 for r in by["sibling"] if r["twin"])),
        "namesake_named": {
            f"born within {matching.FRAUD_YEARS} years": _hits(
                by["namesake"], lambda r: r["years"] <= matching.FRAUD_YEARS, "dob_right"),
            f"born more than {matching.FRAUD_YEARS} years apart": _hits(
                by["namesake"], lambda r: r["years"] > matching.FRAUD_YEARS, "dob_right"),
            "by 'likely the same person'": _hits(by["namesake"], lambda r: True, "likely_right"),
        },
        "on_record_by": {
            "Arabic as on record": _hits(by["on_record"], lambda r: not r["latin"], "likely_right"),
            "Latin letters": _hits(by["on_record"], lambda r: r["latin"], "likely_right"),
            "date exact": _hits(by["on_record"], lambda r: r["dob"] == "exact", "likely_right"),
            "date a typing slip": _hits(by["on_record"], lambda r: r["dob"] == "typing slip", "likely_right"),
            "day and month swapped": _hits(by["on_record"], lambda r: r["dob"] == "day and month swapped",
                                           "likely_right"),
        },
        "age_fraud_by": {
            "1 to 6 months": _hits(by["age_fraud"], lambda r: r["months"] <= 6, "dob_right"),
            "7 to 12 months": _hits(by["age_fraud"], lambda r: 7 <= r["months"] <= 12, "dob_right"),
            "13 to 24 months": _hits(by["age_fraud"], lambda r: 13 <= r["months"] <= 24, "dob_right"),
            "25 to 36 months": _hits(by["age_fraud"], lambda r: r["months"] >= 25, "dob_right"),
            "Arabic as on record": _hits(by["age_fraud"], lambda r: not r["latin"], "dob_right"),
            "Latin letters": _hits(by["age_fraud"], lambda r: r["latin"], "dob_right"),
        },
    }


def _hits(rows: list[dict], which, key: str) -> tuple[int, int]:
    chosen = [r for r in rows if which(r)]
    return sum(r[key] for r in chosen), len(chosen)


def render(summary: dict) -> str:
    def pct(x):
        return "n/a" if x is None else f"{x:.3f}"

    lk, db = summary["likely"], summary["dob"]
    lines = [
        f"Seeds {summary['seeds']}, registers of {min(summary['players'])} to {max(summary['players'])} players; "
        f"planted: {summary['counts']}",
        "",
        "Check                                   precision  recall    F1    (right / raised / should)",
        f"Likely the same person (on record)      {pct(lk['precision']):>9}  {pct(lk['recall']):>6}  {lk['f1']:.3f}"
        f"   {lk['tp']} / {lk['raised']} / {lk['positives']}",
        f"Same name, different date (age fraud)   {pct(db['precision']):>9}  {pct(db['recall']):>6}  {db['f1']:.3f}"
        f"   {db['tp']} / {db['raised']} / {db['positives']}",
        "",
        f"A player on record (either kind) shown to the reviewer by either check: {_share(*summary['either_on_record'])}",
        f"Someone new with anything raised: {_share(*summary['false_alarm_new'])}",
        f"A sibling's record named: {_share(*summary['sibling_named'])}; of them twins: {_share(*summary['twin_named'])}",
        f"Age-fraud plants that also raised 'likely the same person': {lk['raised_on_age_fraud']}",
        "",
        "On record, found by 'likely the same person':",
    ]
    lines += [f"  {k:<24} {_share(*v)}" for k, v in summary["on_record_by"].items()]
    lines.append("Namesakes (two people, one name) named:")
    lines += [f"  {k:<34} {_share(*v)}" for k, v in summary["namesake_named"].items()]
    lines.append("Age fraud, found by 'same name, different date':")
    lines += [f"  {k:<24} {_share(*v)}" for k, v in summary["age_fraud_by"].items()]
    return "\n".join(lines)
