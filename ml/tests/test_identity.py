"""ml/identity: candidates across scripts, the comparison levels, the Fellegi-Sunter model, the
grouping, and the hard-duplicate world. Invented names and records only."""

from __future__ import annotations

import random
from datetime import date

from ml.identity import engine, hard
from ml.identity.engine import Record


def rec(rid, name, *, sex="male", dob=None, sport="football", nat=("EG",), clubs=(), known_as=None):
    return Record(rid, [n for n in (name, known_as) if n], sex=sex, sport=sport, date_of_birth=dob,
                  nationality=frozenset(nat), clubs=frozenset(clubs))


def test_word_keys_are_the_same_in_both_scripts():
    assert engine.word_key("محمد") == engine.word_key("Mohamed") == engine.word_key("Muhammad")
    assert engine.word_key("أحمد") == engine.word_key("Ahmed")
    assert engine.word_key("محمود") != engine.word_key("Khaled")


def test_candidates_cross_scripts_but_respect_sex_and_birth_year():
    a = rec("a", "محمد صلاح", dob=date(2010, 6, 15))
    b = rec("b", "Mohamed Salah", dob=None)
    c = rec("c", "Mohamed Salah", sex="female")
    d = rec("d", "محمد صلاح", dob=date(2005, 1, 1))
    pairs = {tuple(sorted((x.id, y.id))) for x, y in engine.candidates([a, b, c, d])}
    assert ("a", "b") in pairs            # Arabic and Latin meet
    assert ("a", "c") not in pairs        # different sexes are never compared
    assert ("a", "d") not in pairs        # born five years apart, both known
    assert ("b", "d") in pairs            # no date on one side: compared on names


def test_name_levels():
    assert engine.name_level(rec("a", "محمد صلاح"), rec("b", "Mohammed Salah")) == "all"
    assert engine.name_level(rec("a", "أحمد علي حسن"), rec("b", "أحمد حسن")) == "all"
    # A compound left half-dropped still matches on the plain words, as in v1.
    assert engine.name_level(rec("a", "عبد ادم منصور"), rec("b", "عبد الرحمن آدم منصور")) == "all"
    assert engine.name_level(rec("a", "خالد سعيد"), rec("b", "عمر حسن")) == "none"


def test_given_name_separates_relatives():
    brother = rec("a", "Ahmed Bilal Shalaby")
    other = rec("b", "Bilal Ibrahim Shalaby")
    same = rec("c", "أحمد بلال شلبي")
    assert engine.given_level(brother, other) == "different"
    assert engine.given_level(brother, same) == "same"


def test_dob_levels():
    a = rec("a", "x", dob=date(2010, 3, 7))
    assert engine.dob_level(a, rec("b", "x", dob=date(2010, 3, 7))) == "exact"
    assert engine.dob_level(a, rec("b", "x", dob=date(2010, 7, 3))) == "transposed"
    assert engine.dob_level(a, rec("b", "x", dob=date(2010, 3, 10))) == "near"
    assert engine.dob_level(a, rec("b", "x", dob=date(2010, 11, 20))) == "conflict"
    assert engine.dob_level(a, rec("b", "x")) == "unknown"


def _vectors(n_true=200, n_false=2000, seed=3):
    rng = random.Random(seed)
    out = []
    for _ in range(n_true):
        out.append({"name": rng.choices(["all", "most"], [0.9, 0.1])[0], "given": "same",
                    "dob": rng.choices(["exact", "near", "unknown"], [0.5, 0.3, 0.2])[0],
                    "nationality": "same", "club": rng.choice(["same", "different"]), "sport": "same", "sex": "same"})
    for _ in range(n_false):
        out.append({"name": rng.choices(["all", "most", "some", "none"], [0.02, 0.1, 0.6, 0.28])[0],
                    "given": rng.choices(["same", "different"], [0.2, 0.8])[0],
                    "dob": rng.choices(["conflict", "near", "unknown"], [0.85, 0.03, 0.12])[0],
                    "nationality": "same", "club": rng.choices(["same", "different"], [0.1, 0.9])[0],
                    "sport": "same", "sex": "same"})
    return out


def test_em_learns_the_evidence_without_labels():
    model = engine.fit(_vectors())
    assert 0.05 < model.prior < 0.15  # the true share is 200 of 2200, about 0.09
    assert model.weight("name", "all") > 2 and model.weight("name", "none") < 0
    assert model.weight("dob", "conflict") < -1 and model.weight("given", "different") < -1
    # Missing evidence says nothing, and so does a level that never occurred.
    assert model.weight("dob", "unknown") == 0.0
    assert model.weight("dob", "transposed") == 0.0
    assert model.probability(_vectors(1, 0)[0]) > 0.9


def test_grouping_refuses_a_link_that_would_join_conflicting_records():
    a = rec("a", "Mohamed Ali Hassan", dob=date(2010, 1, 1))
    b = rec("b", "Mohamed Ali Hassan")                       # no date: links to both
    c = rec("c", "Mohamed Ali Hassan", dob=date(2010, 9, 20))  # conflicts with a
    pairs = [engine.ScoredPair("a", "b", 0.99, {}), engine.ScoredPair("b", "c", 0.95, {}),
             engine.ScoredPair("a", "c", 0.6, {})]
    groups = engine.group([a, b, c], pairs, link=0.5)
    assert groups == [{"a", "b"}]
    assert engine.pairs_of(groups) == {("a", "b")}


def test_records_read_clubs_and_never_the_merge_record():
    tables = {
        "players": [{"id": "p1", "full_name": "سيف خالد", "known_as": None, "date_of_birth": "2012-02-09",
                     "sex": "male", "primary_sport": "football", "nationality": ["EG"], "status": "merged",
                     "merged_into": "p2"}],
        "affiliations": [{"player_id": "p1", "organization_id": "o1"}],
        "organizations": [{"id": "o1", "name": "Invented FC"}],
    }
    (r,) = engine.records_from_tables(tables)
    assert r.clubs == {"Invented FC"} and r.date_of_birth == date(2012, 2, 9)
    assert not hasattr(r, "status") and not hasattr(r, "merged_into")


def test_latin_spellings_come_from_the_held_out_tables():
    rng = random.Random(1)
    some = next(a for a in hard.TABLE)  # a normalised Arabic name word with spellings
    assert hard.latin(some, rng) in hard.TABLE[some]
    assert hard.latin("كلمةغيرموجودة", rng) is None


def test_harden_changes_a_copy_and_records_what_it_did():
    tables = {"players": [], "affiliations": [], "organizations": [{"id": "o1", "type": "club", "name": "A"}]}
    truth = {"cases": {"duplicates": []}}
    for i in range(40):
        tables["players"].append({"id": f"p{i}", "full_name": "محمد", "date_of_birth": "2010-01-01"})
    hardened, counts, changed = hard.harden(tables, truth, seed=7)
    assert tables["players"][0]["full_name"] == "محمد"  # the input is untouched
    assert counts["clones"] == 0 and changed == {}
    assert counts["other_no_dob"] == sum(1 for p in hardened["players"] if p["date_of_birth"] is None)
    again = hard.harden(tables, truth, seed=7)[0]
    assert again == hardened  # the same seed, the same world
