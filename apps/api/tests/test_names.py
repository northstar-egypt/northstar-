"""Name matching across Arabic and Latin spellings (app/names.py).

The first tests are the evaluation: every Latin spelling in tests/name_spellings.py against
its Arabic name (recall), and against every other name (false matches). Run with -s to see
the numbers:

    cd apps/api && pytest -s tests/test_names.py -k evaluation

The rules in app/names.py were written looking only at the "tune" half. The held-out half
found one bug (Abd glued to a name starting with h read "dh" as one sound), which was fixed
and is reported: held-out recall 96.6% before the fix, 100% after.

The collision lists are exact on purpose. A change that makes two more names collide fails
here instead of quietly widening every name search.

Measured when the rules were frozen (held-out half):

- Word level: 117 of 117 spellings find their name; 0.21% of checks against another name
  match it. Latin against Latin: 0.26%.
- Search level, on the generated dataset: recall 100%, precision 71.2% (92.9% on the tune
  half). Most wrong results come from a Latin double vowel read as an unwritten short one,
  so Hussein finds حسن, Said finds سعد, Mahmoud finds محمد. A rule against that is the obvious
  next step, but it was spotted on the held-out half, and it would cost the French-style
  spellings that write a short vowel as "ou" (Mounir, Moustafa). It needs a fresh set of
  spellings to be judged on, so it is not in.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app import names
from tests.name_spellings import SPELLINGS, half

# Different names a spelling also matches, across scripts. Each pair shares its written
# consonants and differs only in a vowel one side does not write, so no rule based on the
# letters alone can tell them apart without losing real spellings of one of them.
KNOWN_CROSS_SCRIPT = {
    ("Mahmoud", "محمد"), ("Mahmud", "محمد"), ("Mahmood", "محمد"),
    ("Omar", "عمرو"), ("Umar", "عمرو"), ("Amr", "عمر"), ("Amro", "عمر"), ("Amrou", "عمر"),
    ("Amira", "عمر"), ("Amira", "عمرو"), ("Ameera", "عمر"), ("Ameera", "عمرو"),
    ("Hussein", "حسن"), ("Hossein", "حسن"), ("Hussain", "حسن"), ("Hosein", "حسن"),
    ("Ayman", "إيمان"), ("Aiman", "إيمان"), ("Eman", "أيمن"), ("Iman", "أيمن"),
    ("Bassem", "بسمة"), ("Basem", "بسمة"), ("Basim", "بسمة"), ("Basma", "باسم"),
    ("Reham", "رحمة"), ("Riham", "رحمة"),
    ("Nadia", "ندى"), ("Nadya", "ندى"),
    ("Aliaa", "آية"),
    ("El-Sayed", "سعد"), ("Elsayed", "سعد"), ("El Sayed", "سعد"), ("Al-Sayed", "سعد"),
    ("Sayed", "سعد"),
    ("El-Sayed", "سعيد"), ("Elsayed", "سعيد"), ("El Sayed", "سعيد"), ("Al-Sayed", "سعيد"),
    ("Sayed", "سعيد"),
    ("Saeed", "سعد"), ("Said", "سعد"), ("Saied", "سعد"),
    ("Saeed", "السيد"), ("Said", "السيد"), ("Saied", "السيد"),
}


def _score(which: str) -> tuple[int, int, set, int, int]:
    pool = {a: v for a, v in SPELLINGS.items() if which == "all" or half(a) == which}
    hits = total = 0
    for arabic, spellings in pool.items():
        for spelling in spellings:
            total += 1
            hits += names.matches(spelling, arabic) and names.matches(arabic, spelling)
    collisions = {
        (spelling, other)
        for arabic, spellings in pool.items()
        for spelling in spellings
        for other in SPELLINGS
        if other != arabic and names.matches(spelling, other)
    }
    checks = sum(len(s) for s in pool.values()) * (len(SPELLINGS) - 1)
    return hits, total, collisions, checks, len(pool)


@pytest.mark.parametrize("which", ["tune", "held out"])
def test_evaluation_cross_script(which):
    hits, total, collisions, checks, n_names = _score(which)
    print(
        f"\n{which}: {n_names} names, {total} Latin spellings. Recall {hits}/{total} = "
        f"{hits / total:.1%}. Matches a different name: {len(collisions)}/{checks} = "
        f"{len(collisions) / checks:.2%}"
    )
    assert hits == total
    assert collisions <= KNOWN_CROSS_SCRIPT, sorted(collisions - KNOWN_CROSS_SCRIPT)


def test_evaluation_every_known_collision_still_happens():
    """If one disappears, the list above is out of date and should shrink with it."""
    _, _, collisions, _, _ = _score("all")
    assert collisions == KNOWN_CROSS_SCRIPT


def test_evaluation_latin_against_latin():
    """FootyStats spells a name one way, the scout another. Latin against Latin compares
    consonants only, so it cannot tell names apart that differ only in their vowels. The
    number is printed and held, not hidden."""
    hits = total = 0
    for spellings in SPELLINGS.values():
        for a in spellings:
            for b in spellings:
                if a < b:
                    total += 1
                    hits += names.matches(a, b)
    groups = list(SPELLINGS.values())
    false = checks = 0
    for i, first in enumerate(groups):
        for second in groups[i + 1 :]:
            for a in first:
                for b in second:
                    checks += 1
                    false += names.matches(a, b)
    print(
        f"\nLatin against Latin: recall {hits}/{total} = {hits / total:.1%}. Matches a "
        f"different name: {false}/{checks} = {false / checks:.2%}"
    )
    assert hits == total
    assert false / checks <= 0.004


@pytest.fixture(scope="module")
def generated_names():
    """Full and known-as names of a generated dataset, the default seed."""
    pytest.importorskip("faker", reason="the generator needs data/pipelines/requirements.txt")
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root))
    from data.pipelines.synthetic.config import GeneratorConfig
    from data.pipelines.synthetic.dataset import build_dataset

    dataset = build_dataset(GeneratorConfig())
    return [(p.full_name, p.known_as) for p in dataset.players if p.status != "merged"]


def test_evaluation_search_level(generated_names):
    """What a scout sees: search a Latin spelling, and of the players returned, how many
    really carry that name? Word-level false matches are rare (0.2%), but the names that
    collide are common ones (حسن, السيد, سعد), so each collision returns many players."""
    for which in ("tune", "held out"):
        right = wrong = missed = 0
        for arabic, spellings in SPELLINGS.items():
            if half(arabic) != which:
                continue
            truth = {i for i, (full, _) in enumerate(generated_names) if names.matches(arabic, full)}
            for spelling in spellings:
                found = {
                    i for i, (full, known) in enumerate(generated_names)
                    if names.matches(spelling, full, known)
                }
                right += len(found & truth)
                wrong += len(found - truth)
                missed += len(truth - found)
        precision, recall = right / (right + wrong), right / (right + missed)
        print(
            f"\nsearch, {which}, {len(generated_names)} players: precision {right}/"
            f"{right + wrong} = {precision:.1%}, recall {right}/{right + missed} = {recall:.1%}"
        )
        assert recall == 1.0
        # Held at what was measured when the rules were frozen, so a change that makes
        # search worse cannot pass quietly.
        assert precision >= {"tune": 0.90, "held out": 0.69}[which]


def test_the_test_set_covers_every_name_the_generator_uses():
    pytest.importorskip("faker", reason="the generator needs data/pipelines/requirements.txt")
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root))
    from data.pipelines.synthetic.names import FAMILY, FEMALE_GIVEN, MALE_GIVEN

    missing = set(MALE_GIVEN + FEMALE_GIVEN + FAMILY) - set(SPELLINGS)
    assert not missing


@pytest.mark.parametrize(
    "query,name",
    [
        ("Mohamed Salah", "محمد صلاح حامد غالي"),
        ("محمد صلاح", "Mohamed Salah"),
        ("Muhammad", "Mohamed Salah"),
        ("احمد", "أحمد حسن"),  # typed without the hamza
        ("El Shenawy", "محمد الشناوي"),
        ("Abdelrahman", "عبد الرحمن خالد"),
        ("Abd El-Rahman", "Abdulrahman Khaled"),
        ("Kandeel", "قنديل"),
        ("Sa'ad", "سعد"),
    ],
)
def test_the_same_name_matches(query, name):
    assert names.matches(query, name)


@pytest.mark.parametrize(
    "query,name",
    [
        ("Hassan", "حسين"),  # a written long vowel the Latin cannot spell
        ("Ahmed Hassan", "أحمد خالد"),  # every word must match, not just one
        ("Mohamed", "أحمد"),
        ("Saleh", "محمد صلاح"),  # the e cannot spell the long ا that صلاح writes after the l
    ],
)
def test_different_names_do_not(query, name):
    assert not names.matches(query, name)


def test_names_that_differ_only_in_vowels_are_a_known_limit():
    """Held here so it is not mistaken for a bug. Salah (صلاح) and Saleh (صالح) are
    different names whose consonants are the same. Latin against Latin compares consonants
    only, so they match. Across scripts, "Salah" also spells صالح, because its first a can
    stand for the long ا; only a spelling whose vowels rule the Arabic out ("Saleh" against
    صلاح) is told apart."""
    assert names.matches("Salah", "Mohamed Saleh")
    assert names.matches("Salah", "محمد صالح")


def test_a_query_with_no_name_words_matches_nothing():
    assert not names.matches("", "أحمد")
    assert not names.matches("123", "أحمد")


def test_known_as_counts_too():
    assert names.matches("Zizo", "أحمد سيد", "Zizo")


# ---------------------------------------------------------------------------
# Through the search endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def named(db, world):
    """A pro player spelled in Latin, as FootyStats will send him, one academy player in
    Arabic, and a control whose name shares nothing with either."""
    import uuid
    from datetime import timedelta

    from app.models.player import Player
    from tests.conftest import TODAY

    def add(full_name: str, tier: str, age: int) -> Player:
        row = Player(
            id=uuid.uuid4(),
            full_name=full_name,
            date_of_birth=TODAY - timedelta(days=int(age * 365.25)),
            sex="male",
            nationality=["EG"],
            is_egypt_eligible=True,
            primary_sport="football",
            tier=tier,
            position="RW",
            is_minor=age < 18,
            status="active",
        )
        db.add(row)
        return row

    rows = {
        "latin": add("Mohamed Salah Hamed Ghaly", "pro", 33),
        "arabic": add("محمد صلاح الدين قنديل", "pro", 24),
        "control": add("Ahmed Hassan Koka", "pro", 30),
    }
    db.flush()
    return rows


def _ids(client, auth, query: str) -> tuple[set[str], dict]:
    body = client.post(
        "/search", json={"query": query, "limit": 200, "includeMinors": True}, headers=auth("admin")
    ).json()
    return {r["player"]["id"] for r in body["results"]}, body


def test_an_arabic_query_finds_a_name_stored_in_latin(client, auth, named):
    found, body = _ids(client, auth, "محمد صلاح")
    assert str(named["latin"].id) in found
    assert str(named["arabic"].id) in found
    assert str(named["control"].id) not in found
    assert [c["label"] for c in body["parsed"]["chips"]] == ["name: محمد", "name: صلاح"]


def test_a_latin_query_finds_a_name_stored_in_arabic(client, auth, named):
    found, _ = _ids(client, auth, "Mohammed Salah")
    assert str(named["arabic"].id) in found
    assert str(named["latin"].id) in found
    assert str(named["control"].id) not in found


def test_an_arabic_name_narrows_the_search_instead_of_being_dropped(client, auth, named):
    """It used to vanish without a chip, and the screen showed every player."""
    everyone, _ = _ids(client, auth, "")
    found, body = _ids(client, auth, "قنديل")
    assert str(named["arabic"].id) in found
    assert len(found) < len(everyone)
    assert body["parsed"]["chips"] == [{"label": "name: قنديل", "understood": True}]


def test_name_terms_combine_with_the_other_filters(client, auth, named):
    found, _ = _ids(client, auth, "Mohamed under 30")
    assert str(named["arabic"].id) in found
    assert str(named["latin"].id) not in found  # 33
