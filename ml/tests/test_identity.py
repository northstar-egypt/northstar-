"""ml/identity: candidates across scripts, the comparison levels, the Fellegi-Sunter model, the
grouping, and the hard-duplicate world. Invented names and records only."""

from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from ml.identity import engine, hard, labels
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


def test_name_levels_leave_the_given_name_to_its_own_field():
    assert engine.name_level(rec("a", "محمد صلاح حامد"), rec("b", "Mohammed Salah Hamed")) == "all"
    assert engine.name_level(rec("a", "محمد صلاح"), rec("b", "Mohammed Salah")) == "all-one-word"
    assert engine.name_level(rec("a", "أحمد علي حسن محمود"), rec("b", "أحمد حسن محمود")) == "all"
    # A compound left half-dropped still matches on the plain words, as in v1.
    assert engine.name_level(rec("a", "سيف عبد ادم منصور"), rec("b", "سيف عبد الرحمن آدم منصور")) == "all"
    assert engine.name_level(rec("a", "خالد سعيد"), rec("b", "عمر حسن")) == "none"
    # Two players who share only a first name share nothing here: "José" is counted once, in
    # the given name, not twice. Counted twice, it linked hundreds of professionals.
    assert engine.name_level(rec("a", "José Luis Morales"), rec("b", "José Ángel Crespo")) == "none"
    assert engine.name_level(rec("a", "Kaká"), rec("b", "Kaká Leite")) == "unknown"


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


def _register(n=300, seed=5):
    """Invented records: n people with three-word names drawn from about a hundred name words."""
    rng = random.Random(seed)
    words = [w for w in hard.TABLE if " " not in w and w not in ("صلاح", "حامد")]
    out = []
    for i in range(n):
        name = " ".join(rng.sample(words, 3))
        out.append(rec(f"p{i}", name, dob=date(2009, 1, 1) + timedelta(days=rng.randrange(1500))))
    return out


def test_random_u_is_measured_on_random_pairs():
    records = _register()
    u = engine.random_u(records, pairs=4000)
    assert abs(sum(u["dob"].values()) - 1) < 1e-9
    # Random people almost never share a whole name or a birthday; they nearly always share a sport.
    assert u["name"]["all"] < 0.05 and u["dob"]["exact"] < 0.01
    assert u["sport"]["same"] > 0.9


def test_measured_scoring_puts_the_share_over_every_pair():
    """With u from random pairs the share of true pairs is the chance two random records are one
    person: tiny, not the share among candidates. Mixing the two linked thousands of people."""
    records = _register()
    records.append(rec("copy", "Mohamed Mansour Shalaby"))
    scored, model = engine.score(records)
    n = len(records)
    assert model.prior < 50 / (n * (n - 1) / 2)
    assert engine.score(records, method="em")[1].prior > model.prior


def test_measured_m_is_read_from_the_calibration_file():
    m = engine.measured_m()
    assert set(m) == set(engine.FIELDS)
    assert m["name"]["all"] > m["name"]["some"] and m["given"]["same"] > 0.9


def test_proposals_leave_out_merged_records_and_explain_themselves():
    tables = {
        "players": [
            {"id": "a", "full_name": "محمد صلاح حامد", "date_of_birth": "2011-03-07", "sex": "male",
             "primary_sport": "football", "nationality": ["EG"]},
            {"id": "b", "full_name": "Mohamed Salah Hamed", "date_of_birth": None, "sex": "male",
             "primary_sport": "football", "nationality": ["EG"]},
            {"id": "c", "full_name": "محمد صلاح حامد", "date_of_birth": "2011-03-07", "sex": "male",
             "primary_sport": "football", "nationality": ["EG"], "status": "merged"},
        ] + [{"id": f"x{i}", "full_name": r.names[0], "date_of_birth": r.date_of_birth.isoformat(), "sex": "male",
              "primary_sport": "football", "nationality": ["EG"]} for i, r in enumerate(_register(200))],
        "affiliations": [], "organizations": [],
    }
    links, records = engine.propose(tables)
    pairs = {tuple(sorted((s.a, s.b))) for s in links}
    assert ("a", "b") in pairs
    assert not any("c" in p for p in pairs)
    link = next(s for s in links if {s.a, s.b} == {"a", "b"})
    points = engine.evidence(link, records["a"], records["b"])
    assert any("Arabic" in p and "Latin" in p for p in points)
    assert "No date of birth on one record, so the date could not be checked" in points


# ---------------------------------------------------------------------------
# Real labels (ml/identity/labels.py), on invented records
# ---------------------------------------------------------------------------


def _player(pid, name, source=None, nat=("EG",), dob=None):
    ids = {source: pid} if source else {}
    return {"id": pid, "full_name": name, "external_ids": ids, "nationality": list(nat),
            "date_of_birth": dob, "sex": "male", "primary_sport": "football"}


def test_anchors_are_unique_full_names_in_both_sources():
    tables = {"players": [
        _player("f1", "Invented Playerone", "footystats"), _player("s1", "Invented Playerone", "statsbomb"),
        _player("f2", "Common Name", "footystats"), _player("f3", "Common Name", "footystats"),
        _player("s2", "Common Name", "statsbomb"),                      # not unique in FootyStats
        _player("f4", "Single", "footystats"), _player("s4", "Single", "statsbomb"),  # one word
        _player("f5", "Sam Ádàm", "footystats"), _player("s5", "Sam Adam", "statsbomb"),  # accents
    ]}
    assert labels.anchors(tables) == [("f1", "s1"), ("f5", "s5")]


def test_the_sample_refuses_a_folder_git_could_track(tmp_path):
    inside = Path(__file__).resolve().parents[2] / "ml" / "identity" / "labels-here"
    with pytest.raises(ValueError, match="outside the repository"):
        labels.sample({"players": []}, inside)
    assert not inside.exists()


def test_strata_follow_what_the_engine_made_of_a_pair():
    p = engine.ScoredPair("a", "b", 0.95, {"name": "all", "given": "same"})
    assert labels.stratum(p, {("a", "b")}) == "linked-strong"
    assert labels.stratum(engine.ScoredPair("a", "b", 0.6, {}), {("a", "b")}) == "linked-weak"
    near = engine.ScoredPair("a", "b", 0.1, {"name": "all-one-word", "given": "same"})
    assert labels.stratum(near, set()) == "near-whole-name"
    assert labels.stratum(engine.ScoredPair("a", "b", 0.1, {"name": "most", "given": "same"}), set()) == "near-most-name"
    assert labels.stratum(engine.ScoredPair("a", "b", 0.1, {"name": "some", "given": "same"}), set()) is None


def test_the_estimate_weights_each_stratum_by_its_size(tmp_path):
    """Two of four strong links are right, and the strong stratum is 100 pairs: 50 true. One of
    two near misses is a true pair, of 40: 20 missed. Precision 50/100, recall 50/70."""
    pairs, rows = {}, []
    for i, (k, same) in enumerate([("linked-strong", "yes"), ("linked-strong", "no"), ("linked-strong", "yes"),
                                   ("linked-strong", "no"), ("near-whole-name", "yes"), ("near-whole-name", "no"),
                                   ("linked-weak", "unsure")]):
        pairs[f"p{i}"] = {"stratum": k}
        rows.append({"pair_id": f"p{i}", "same_person": same})
    meta = {"strata": {"linked-strong": {"size": 100}, "linked-weak": {"size": 0},
                       "near-whole-name": {"size": 40}, "near-most-name": {"size": 0}},
            "pairs": pairs, "m_file": ""}
    (tmp_path / "sample.json").write_text(json.dumps(meta), encoding="utf-8")
    with (tmp_path / "pairs.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["pair_id", "same_person"])
        w.writeheader()
        w.writerows(rows)
    result = labels.score(tmp_path, reps=200)
    assert result["point"]["precision"] == pytest.approx(0.5)
    assert result["point"]["recall"] == pytest.approx(50 / 70)
    assert result["unsure_or_blank"] == 1
    lo, hi = result["interval"]["precision"]
    assert lo < 0.5 < hi


def test_a_rare_word_counts_for_more_than_a_common_one():
    records = [rec(f"x{i}", f"Ahmed Silva{'' if i % 2 else ' Junior'}") for i in range(40)]
    records += [rec("r", "Nabil Qozmarwi"), rec("q", "Nabil Qozmarwi", nat=("NL",))]
    shares = engine.term_shares(records)
    u_avg = sum(x * x for x in shares.values())
    rare = engine.tf_offset(records[-2], records[-1], "all-one-word", shares, u_avg)
    common = engine.tf_offset(records[1], records[3], "all-one-word", shares, u_avg)
    assert rare > 0 > common
    assert engine.tf_offset(records[-2], records[-1], "all", shares, u_avg) == 0.0
