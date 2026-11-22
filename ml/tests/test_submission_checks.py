"""The diaspora submission checks (ml/identity/submissions.py) and their evaluation's planting
(ml/submission_eval.py), on invented records. The graded numbers come from
`python -m ml.run_submission_eval` (ml/README.md, "Diaspora submission checks")."""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from ml import submission_eval
from ml.identity import engine
from ml.identity import submissions as matching

GIVEN = ["Ahmed", "Omar", "Youssef", "Mostafa", "Ali", "Hassan", "Mahmoud", "Tarek", "Sherif", "Hany"]
FAMILY = ["Ibrahim", "Saleh", "Fathy", "Nabil", "Samir", "Gamal", "Lotfy", "Rashad", "Wahba", "Zaki"]
BORN = date(2004, 3, 10)


@pytest.fixture(scope="module")
def register():
    rng = random.Random(5)
    records = {}
    for i in range(300):
        records[f"p{i}"] = engine.Record(
            id=f"p{i}", names=[f"{rng.choice(GIVEN)} {rng.choice(FAMILY)} {rng.choice(FAMILY)}"], sex="male",
            sport="football", date_of_birth=date(1998, 1, 1) + timedelta(days=rng.randint(0, 4000)),
            nationality=frozenset(["EG"]), clubs=frozenset([f"Club {rng.randint(0, 30)}"]))
    records["karim"] = engine.Record(id="karim", names=["Karim Adel Mansour"], sex="male", sport="football",
                                     date_of_birth=BORN, nationality=frozenset(["EG"]), clubs=frozenset(["Academy A"]))
    return records, matching.fit(list(records.values()))


def _submitted(name="Karim Adel Mansour", born=BORN):
    return engine.Record(id="new", names=[name], sex="male", sport="football", date_of_birth=born,
                         nationality=frozenset(["EG", "DE"]), clubs=frozenset(["FC Abroad"]))


def _checks(register, record):
    records, fitted = register
    likely, twins = matching.classify(matching.score_one(record, records, fitted))
    return [p.b for p in likely], [p.b for p in twins]


def test_a_register_with_no_duplicates_can_still_match(register):
    _, fitted = register
    n = fitted.records
    assert fitted.model.prior >= 0.1 * n / (n * (n - 1) // 2)


@pytest.mark.parametrize(("days", "likely", "twin"), [
    (0, True, False),        # the same person
    (4, True, False),        # a typing slip
    (150, False, True),      # five months younger on paper
    (900, False, True),      # about two and a half years: outside the engine's blocking
    (4 * 365, False, False), # beyond FRAUD_YEARS: not compared at all
])
def test_the_date_of_birth_decides_which_check_names_the_record(register, days, likely, twin):
    found, twins = _checks(register, _submitted(born=BORN + timedelta(days=days)))
    assert ("karim" in found) is likely
    assert ("karim" in twins) is twin


def test_a_brother_is_named_by_neither_check(register):
    found, twins = _checks(register, _submitted(name="Omar Adel Mansour", born=BORN + timedelta(days=500)))
    assert "karim" not in found and "karim" not in twins


def test_someone_unknown_is_named_by_neither(register):
    assert _checks(register, _submitted(name="Zoltan Quetzal Brightwater")) == ([], [])


def _tables():
    rng = random.Random(9)
    players = [{"id": f"p{i}", "full_name": f"{rng.choice(GIVEN)} {rng.choice(FAMILY)} {rng.choice(FAMILY)}",
                "date_of_birth": (date(2000, 1, 1) + timedelta(days=rng.randint(0, 3000))).isoformat(),
                "sex": "male", "primary_sport": "football", "nationality": ["EG"]} for i in range(120)]
    return {"players": players, "affiliations": [], "organizations": []}


def test_the_planting_makes_what_it_says():
    tables = _tables()
    plants = submission_eval.plant(tables, seed=3)
    kinds = {k: [p for p in plants if p.kind == k] for k in submission_eval.PLANTS}
    assert {k: len(v) for k, v in kinds.items()} == submission_eval.PLANTS
    on_record = {p["full_name"] for p in tables["players"]}
    # Someone new is nobody's name on record; a sibling keeps the family name, not the given name.
    assert not {p.record.names[0] for p in kinds["new"] if not p.detail["latin"]} & on_record
    by_id = {p["id"]: p for p in tables["players"]}
    for p in kinds["sibling"]:
        if not p.detail["latin"]:
            assert p.record.names[0].split()[1:] == by_id[p.target]["full_name"].split()[1:]
            assert p.record.names[0].split()[0] != by_id[p.target]["full_name"].split()[0]
    for p in kinds["age_fraud"]:
        shift = (p.record.date_of_birth - date.fromisoformat(by_id[p.target]["date_of_birth"])).days
        assert 1 <= p.detail["months"] <= 36 and shift > 0
    assert submission_eval.plant(tables, seed=3)[0].record == plants[0].record  # same seed, same plants
