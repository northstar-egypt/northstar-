"""Which records are the same person: find candidates, score them, group them into people.

The duplicate detector v1 (ml/detectors/duplicate.py) handles the duplicates the generator
plants: the same Arabic name typed again with a spelling difference, a date of birth a few days
off. A national register meets harder ones, and the platform already holds some: the same
person spelled in Latin by one source and in Arabic by another, a source with no date of birth
(StatsBomb), a player registered at a different club. v1 cannot see any of them: it blocks on
the birth year and needs the Arabic-normalised names to match outright.

1. Candidates (blocking)
------------------------
Every name word gets a key that is the same in both scripts: its first two consonant sounds,
read by app/names.py, without h, w and y (which Latin spellings drop or turn into vowels). So
محمد and Mohamed are both "mm", and أحمد and Ahmed both "md". Two records are compared when they
share as many keys as the shorter name has words (two at most), are not of different sexes, and
were born within a year of each other when both dates are known. Records with no date are
compared on names alone, which is what lets a StatsBomb player meet their FootyStats record.

2. Score (Fellegi-Sunter)
-------------------------
The standard probabilistic method of record linkage. Each candidate pair is described by how far
it agrees on each piece of evidence, as a level:

- name, after the given name: every word of the shorter matches a word of the longer, in either
  script (app/names.py), with two words or more; the same with one word only; most words; some;
  none; unknown (a one-word name has nothing after the given name);
- given name: the first word the same, different, or unknown (Egyptian names run given name,
  father, grandfather, so relatives share everything but this);
- date of birth: exact; day and month transposed; within a week; both known and none of these
  (a conflict); unknown (either side has none);
- nationality, club (any organisation name in common), sport and sex: the same, different, or
  unknown.

The given name is in its own field and not in the name field, because the method takes its
pieces of evidence to be independent: counted in both, one shared "José" was two strong pieces
of evidence, and on the professionals that alone linked hundreds of different people.

For each level the method needs two probabilities: how often a true pair shows it (m) and how
often a false pair does (u), and the chance that two records are one person at all. How they
are estimated decides whether the engine works on real data (`score`):

- u is measured on random pairs of the records being matched (`random_u`), which are almost
  all different people. This is the standard way to estimate u without labels.
- m is measured on the known duplicate pairs of the calibration seeds 101, 202 and 303, both
  worlds (`measured_m`, ml/identity/m_probabilities.json). How a re-entered record differs from
  the first is a property of data entry, not of the population, so it carries over; how often
  unrelated people share a name does not carry over, which is why u is measured afresh. For
  nationality and club, the generated data never varies the way real sources do (StatsBomb
  records a player's national team, FootyStats his birth country), so the anchor pairs of a
  real export are counted in too (ml/identity/labels.py, `anchors`).
- a match on one name word after the given name is adjusted for how common the word is
  (`tf_offset`): "Mazraoui" is stronger evidence than "Silva".
- the chance two random records are one person is estimated by expectation-maximisation over
  every pair (a pair blocking leaves out counts as two people).

#117 estimated all three by expectation-maximisation on the candidates, with no labels. It
graded well on the generated register and failed on the professionals: it settled on "same
first name" rather than "same person" and proposed 6,086 links on the demo database, 4,354 of
them between two StatsBomb records, which are certainly different people. That method is kept
as `method="em"` so the comparison can be rerun (ml/run_identity_eval.py).

The pair's score is the probability that it is one person, assuming the pieces of evidence are
independent given the answer (the method's standard assumption, and its known weakness).

3. Group
--------
Pairs scoring at least `link` are joined into groups (one person, any number of records),
strongest link first, and a link that would put two records that conflict outright (different
known sexes, or both dates known and unrelated) into one group is refused.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ml import sport_modules  # noqa: F401  (puts apps/api on the path)
from ml.detectors.duplicate import dob_relation, name_tokens

from app import names  # noqa: E402

DOB_WINDOW_DAYS = 7
MAX_POSTING = 5000


@dataclass
class Record:
    id: str
    names: list[str]
    sex: str | None = None
    sport: str | None = None
    date_of_birth: date | None = None
    nationality: frozenset[str] = frozenset()
    clubs: frozenset[str] = frozenset()
    source: str | None = None
    words: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.words:
            seen = []
            for n in self.names:
                for w in names.words(n or ""):
                    if w not in seen:
                        seen.append(w)
            self.words = seen


# ---------------------------------------------------------------------------
# 1. Candidates
# ---------------------------------------------------------------------------


def _sounds(word: str) -> list[str]:
    if names._is_arabic(word):
        units = names._arabic_units(word)
    else:
        units = names._latin_units(word.lower())
    return [u[1] for u in units if u[0] == "c" and u[1] not in ("h", "w", "y")]


def word_key(word: str) -> str:
    """The first two consonant sounds, the same for محمد and Mohamed ("mm")."""
    return "".join(_sounds(word)[:2])


def keys(record: Record) -> set[str]:
    return {k for w in record.words if (k := word_key(w))}


def _compatible(a: Record, b: Record) -> bool:
    if a.sex and b.sex and a.sex != b.sex:
        return False
    if a.date_of_birth and b.date_of_birth and abs(a.date_of_birth.year - b.date_of_birth.year) > 1:
        return False
    return True


def candidates(records: list[Record]) -> list[tuple[Record, Record]]:
    """Pairs worth scoring: enough shared name keys, and nothing ruling them out cheaply."""
    index: dict[str, list[int]] = defaultdict(list)
    record_keys = [keys(r) for r in records]
    for i, ks in enumerate(record_keys):
        for k in ks:
            index[k].append(i)
    shared: dict[tuple[int, int], int] = defaultdict(int)
    for posting in index.values():
        if len(posting) > MAX_POSTING:
            continue
        for x in range(len(posting)):
            for y in range(x + 1, len(posting)):
                shared[(posting[x], posting[y])] += 1
    out = []
    for (i, j), n in shared.items():
        need = min(2, len(record_keys[i]), len(record_keys[j]))
        if n >= need and _compatible(records[i], records[j]):
            out.append((records[i], records[j]))
    return out


# ---------------------------------------------------------------------------
# 2. Comparison levels and Fellegi-Sunter
# ---------------------------------------------------------------------------

FIELDS = ("name", "given", "dob", "nationality", "club", "sport", "sex")


_NAME_ORDER = ("all", "all-one-word", "most", "some", "none")


def _level(hits: int, of: int) -> str:
    if not of:
        return "none"
    if hits == of:
        return "all" if hits >= 2 else "all-one-word"
    return "most" if hits / of >= 0.6 else "some" if hits else "none"


# The name field leaves out the given name, which has its own field. Counted in both, one shared
# first word ("José", "Mohamed") was two pieces of evidence, and the model takes its pieces to be
# independent. On the professionals, where many players share a first name and nothing else,
# that alone linked hundreds of different people.
def _rest(words: list[str]) -> list[str]:
    return words[1:]


def name_level(a: Record, b: Record) -> str:
    """The better of two readings: name words matched across scripts (app/names.py, which keeps
    عبد with the word after it), and the plain words v1 compares after Arabic normalisation. A
    name with part of a compound dropped ("عبد" left without "الرحمن") only matches the second
    way, so the engine never sees less than v1 does. The given name is left out (above); a
    record with nothing after it says nothing here."""
    wa, wb = _rest(a.words), _rest(b.words)
    if not wa or not wb:
        return "unknown"
    short, long = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    cross = _level(sum(1 for w in short if any(names.word_matches(w, v) for v in long)), len(short))
    ta = _rest([t for n in a.names for t in name_tokens(n)])
    tb = _rest([t for n in b.names for t in name_tokens(n)])
    ts, tl = (ta, tb) if len(set(ta)) <= len(set(tb)) else (tb, ta)
    plain = _level(len(set(ts) & set(tl)), len(set(ts))) if ts else "none"
    return min(cross, plain, key=_NAME_ORDER.index)


def given_level(a: Record, b: Record) -> str:
    """The first word of the full name, the given name. Egyptian names run given name, father,
    grandfather: brothers and cousins share all but the first word, so a different given name is
    strong evidence of a different person even when the rest matches."""
    fa = names.words(a.names[0])[:1] if a.names else []
    fb = names.words(b.names[0])[:1] if b.names else []
    if not fa or not fb:
        return "unknown"
    return "same" if names.word_matches(fa[0], fb[0]) else "different"


def dob_level(a: Record, b: Record) -> str:
    if a.date_of_birth is None or b.date_of_birth is None:
        return "unknown"
    relation = dob_relation(a.date_of_birth, b.date_of_birth, DOB_WINDOW_DAYS)
    return {"exact": "exact", "within_days": "near", "day_month_transposed": "transposed"}.get(relation, "conflict")


def _set_level(x: frozenset, y: frozenset) -> str:
    if not x or not y:
        return "unknown"
    return "same" if x & y else "different"


def _value_level(x, y) -> str:
    if not x or not y:
        return "unknown"
    return "same" if x == y else "different"


def compare(a: Record, b: Record) -> dict[str, str]:
    return {
        "name": name_level(a, b),
        "given": given_level(a, b),
        "dob": dob_level(a, b),
        "nationality": _set_level(a.nationality, b.nationality),
        "club": _set_level(a.clubs, b.clubs),
        "sport": _value_level(a.sport, b.sport),
        "sex": _value_level(a.sex, b.sex),
    }


LEVELS = {
    "name": ("all", "all-one-word", "most", "some", "none", "unknown"),
    "given": ("same", "different", "unknown"),
    "dob": ("exact", "transposed", "near", "conflict", "unknown"),
    "nationality": ("same", "different", "unknown"),
    "club": ("same", "different", "unknown"),
    "sport": ("same", "different", "unknown"),
    "sex": ("same", "different", "unknown"),
}

# Starting points for EM only: a true pair mostly agrees, a false one mostly does not.
_M0 = {
    "name": {"all": 0.8, "all-one-word": 0.05, "most": 0.1, "some": 0.03, "none": 0.01, "unknown": 0.01},
    "given": {"same": 0.9, "different": 0.05, "unknown": 0.05},
    "dob": {"exact": 0.4, "transposed": 0.1, "near": 0.25, "conflict": 0.05, "unknown": 0.2},
    "nationality": {"same": 0.85, "different": 0.05, "unknown": 0.1},
    "club": {"same": 0.5, "different": 0.3, "unknown": 0.2},
    "sport": {"same": 0.95, "different": 0.03, "unknown": 0.02},
    "sex": {"same": 0.97, "different": 0.01, "unknown": 0.02},
}
_U0 = {
    "name": {"all": 0.05, "all-one-word": 0.05, "most": 0.2, "some": 0.45, "none": 0.2, "unknown": 0.05},
    "given": {"same": 0.3, "different": 0.65, "unknown": 0.05},
    "dob": {"exact": 0.01, "transposed": 0.005, "near": 0.03, "conflict": 0.75, "unknown": 0.205},
    "nationality": {"same": 0.7, "different": 0.2, "unknown": 0.1},
    "club": {"same": 0.1, "different": 0.7, "unknown": 0.2},
    "sport": {"same": 0.7, "different": 0.28, "unknown": 0.02},
    "sex": {"same": 0.9, "different": 0.08, "unknown": 0.02},
}


@dataclass
class Model:
    m: dict[str, dict[str, float]]
    u: dict[str, dict[str, float]]
    prior: float
    iterations: int = 0
    # Levels that occurred among the candidate pairs; any other says nothing.
    seen: dict[str, frozenset[str]] = field(default_factory=dict)

    def weight(self, field_: str, level: str) -> float:
        """How much a level says, in log odds: positive for evidence of one person.

        Missing evidence ("unknown") is neutral by definition, the standard treatment in record
        linkage: whether a source records a date of birth says nothing about whether two records
        are one person. So is a level that never occurred, whose estimate would be only the
        smoothing."""
        if level == "unknown" or (self.seen and level not in self.seen.get(field_, frozenset())):
            return 0.0
        return math.log(self.m[field_][level] / self.u[field_][level])

    def probability(self, vector: dict[str, str], offset: float = 0.0) -> float:
        """`offset` is added to the log odds: the term-frequency adjustment (`tf_offset`)."""
        log_odds = math.log(self.prior / (1 - self.prior)) + sum(self.weight(f, vector[f]) for f in FIELDS) + offset
        return 1 / (1 + math.exp(-max(-50.0, min(50.0, log_odds))))


def fit(
    vectors: list[dict[str, str]],
    iterations: int = 200,
    prior: float = 0.05,
    smoothing: float = 0.5,
    u: dict[str, dict[str, float]] | None = None,
    all_pairs: int | None = None,
    m: dict[str, dict[str, float]] | None = None,
    offsets: list[float] | None = None,
) -> Model:
    """Estimate m, u and the share of true pairs by expectation-maximisation, with no labels.

    `smoothing` adds a small count to every level, so a level never seen in one class does not
    get a probability of zero (which would make it infinitely decisive). With `u` given (from
    random pairs, `random_u`), only m and the share are estimated and u is held fixed.

    Identical vectors are counted once with their multiplicity: there are a few thousand
    possible patterns and tens of thousands of pairs, so this is the same computation, faster."""
    fixed_u, fixed_m = u is not None, m is not None
    m = {f: dict(m[f]) for f in FIELDS} if fixed_m else {f: dict(_M0[f]) for f in FIELDS}
    u = {f: dict(u[f]) for f in FIELDS} if fixed_u else {f: dict(_U0[f]) for f in FIELDS}
    seen = {f: frozenset(v[f] for v in vectors) for f in FIELDS}
    model = Model(m, u, prior, seen=seen)
    if not vectors:
        return model
    patterns = defaultdict(int)
    for v, o in zip(vectors, offsets or [0.0] * len(vectors)):
        patterns[(tuple(v[f] for f in FIELDS), round(o, 2))] += 1
    rows = [(dict(zip(FIELDS, key)), o, n) for (key, o), n in patterns.items()]
    for it in range(iterations):
        posts = [(v, n, model.probability(v, o)) for v, o, n in rows]
        total = sum(n * p for _, n, p in posts)
        if all_pairs:
            # u describes random pairs, so the share is over every pair of records, not over
            # the candidates (a pair left out by blocking is taken to be two people).
            new_prior = min(0.5, max(1e-12, total / all_pairs))
        else:
            new_prior = min(0.5, max(1e-4, total / len(vectors)))
        new_m, new_u = {}, {}
        for f in FIELDS:
            cm = {lvl: smoothing for lvl in LEVELS[f]}
            cu = {lvl: smoothing for lvl in LEVELS[f]}
            for v, n, p in posts:
                cm[v[f]] += n * p
                cu[v[f]] += n * (1 - p)
            sm, su = sum(cm.values()), sum(cu.values())
            new_m[f] = model.m[f] if fixed_m else {k: c / sm for k, c in cm.items()}
            new_u[f] = model.u[f] if fixed_u else {k: c / su for k, c in cu.items()}
        change = abs(new_prior - model.prior) / (model.prior if all_pairs else 1.0)
        model = Model(new_m, new_u, new_prior, it + 1, seen)
        if change < 1e-7:
            break
    return model


RANDOM_PAIRS = 50000


def random_u(records: list[Record], pairs: int = RANDOM_PAIRS, seed: int = 0, smoothing: float = 0.5) -> dict:
    """How often two records of different people agree on each piece of evidence, measured on
    random pairs of records, almost all of which are different people. This is the standard way
    to estimate u without labels (it is what Splink does): estimated by EM on the candidates
    alone, u describes the candidates, which share names by construction. With u from random
    pairs, the share of true pairs is over every pair of records (`fit`, `all_pairs`).

    A level random pairs almost never show (the whole name the same) is estimated from the
    smoothing alone, so the strongest weights depend on `pairs`: at 50,000, about +11."""
    import random

    rng = random.Random(seed)
    counts = {f: {lvl: smoothing for lvl in LEVELS[f]} for f in FIELDS}
    n = len(records)
    if n < 2:
        return {f: {lvl: 1 / len(LEVELS[f]) for lvl in LEVELS[f]} for f in FIELDS}
    for _ in range(pairs):
        i, j = rng.sample(range(n), 2)
        for f, lvl in compare(records[i], records[j]).items():
            counts[f][lvl] += 1
    return {f: {lvl: c / sum(cs.values()) for lvl, c in cs.items()} for f, cs in counts.items()}


@dataclass
class ScoredPair:
    a: str
    b: str
    probability: float
    levels: dict[str, str]


M_FILE = Path(__file__).with_name("m_probabilities.json")


def measured_m() -> dict[str, dict[str, float]]:
    """m measured on the calibration seeds' known duplicate pairs, both worlds
    (`python -m ml.run_identity_eval --fit-m` writes it)."""
    if not M_FILE.exists():
        raise FileNotFoundError(f"{M_FILE} is missing: run python -m ml.run_identity_eval --fit-m")
    m = json.loads(M_FILE.read_text(encoding="utf-8"))["m"]
    return {f: {lvl: m[f][lvl] for lvl in LEVELS[f]} for f in FIELDS}


def term_shares(records: list[Record]) -> dict[str, float]:
    """How common each name word is, after the given name: its share of all such words, counted
    once per record, read by its consonant sounds so a word weighs the same in both scripts."""
    counts: dict[str, int] = defaultdict(int)
    for r in records:
        for k in {skeleton(w) for w in _rest(r.words)}:
            counts[k] += 1
    total = sum(counts.values()) or 1
    return {k: c / total for k, c in counts.items()}


def skeleton(word: str) -> str:
    return "".join(_sounds(word))


def tf_offset(a: Record, b: Record, level: str, shares: dict[str, float], u_avg: float) -> float:
    """The term-frequency adjustment, the standard one in record linkage (Splink uses it): when
    the name after the given name is one word and it matches, a rare word ("Mazraoui") is
    stronger evidence than a common one ("Silva"). The level's weight assumes an average word;
    this adds log(average chance two different people share a word / this word's chance), which
    is positive for a rare word and negative for a common one. Only for the one-word level, where
    a single word is all the name evidence there is."""
    if level != "all-one-word":
        return 0.0
    wa, wb = _rest(a.words), _rest(b.words)
    short, long = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    if len(short) != 1:
        return 0.0
    share = shares.get(skeleton(short[0]))
    if not share or not u_avg:
        return 0.0
    return math.log(u_avg / share)


def score(
    records: list[Record], model: Model | None = None, method: str = "measured-tf"
) -> tuple[list[ScoredPair], Model]:
    """Every candidate pair with its probability of being one person.

    `measured-tf` (the default): m as measured on the calibration seeds' known pairs and the
    anchors (ml/identity/labels.py), u from random pairs of these records, the share of true pairs
    estimated by EM over every pair, and the term-frequency adjustment (`tf_offset`). `measured`:
    the same without the adjustment. `em`:
    m, u and the share all estimated by EM on the candidates, with no labels at all (#117), which
    on the professionals settles on "same first name" (ml/README.md, "Player identity")."""
    pairs = candidates(records)
    vectors = [compare(a, b) for a, b in pairs]
    offsets = [0.0] * len(pairs)
    if method == "measured-tf":
        shares = term_shares(records)
        u_avg = sum(x * x for x in shares.values())
        offsets = [tf_offset(a, b, v["name"], shares, u_avg) for (a, b), v in zip(pairs, vectors)]
    if model is None and method in ("measured", "measured-tf"):
        n = len(records)
        everything = max(1, n * (n - 1) // 2)
        model = fit(vectors, m=measured_m(), u=random_u(records), all_pairs=everything,
                    prior=min(0.5, max(1e-12, 0.1 * n / everything)), offsets=offsets)
    elif model is None and method == "em":
        model = fit(vectors)
    elif model is None:
        raise ValueError(f"unknown method {method!r}")
    return [ScoredPair(a.id, b.id, model.probability(v, o), v)
            for (a, b), v, o in zip(pairs, vectors, offsets)], model


# ---------------------------------------------------------------------------
# 3. Group
# ---------------------------------------------------------------------------


def _conflict(a: Record, b: Record) -> bool:
    if a.sex and b.sex and a.sex != b.sex:
        return True
    return dob_level(a, b) == "conflict"


def _components(ids: list[str], edges: list[tuple[str, str]]) -> list[set[str]]:
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups: dict[str, set[str]] = defaultdict(set)
    for i in ids:
        groups[find(i)].add(i)
    return [g for g in groups.values() if len(g) > 1]


def group(records: list[Record], pairs: list[ScoredPair], link: float) -> list[set[str]]:
    """People: groups of two or more records, each free of outright conflicts.

    Links are taken strongest first; two groups are joined by a link only if no record of one
    conflicts with a record of the other (different known sexes, or both dates known and
    unrelated). A plain chain of links could join two people through a third record that looks
    like both; this cannot."""
    by_id = {r.id: r for r in records}
    members: dict[str, set[str]] = {r.id: {r.id} for r in records}
    for p in sorted((p for p in pairs if p.probability >= link), key=lambda p: -p.probability):
        ga, gb = members[p.a], members[p.b]
        if ga is gb:
            continue
        if any(_conflict(by_id[x], by_id[y]) for x in ga for y in gb):
            continue
        merged = ga | gb
        for x in merged:
            members[x] = merged
    seen, out = set(), []
    for g in members.values():
        if len(g) > 1 and id(g) not in seen:
            seen.add(id(g))
            out.append(g)
    return out


def pairs_of(groups: list[set[str]]) -> set[tuple[str, str]]:
    out = set()
    for g in groups:
        members = sorted(g)
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                out.add((members[i], members[j]))
    return out


# ---------------------------------------------------------------------------
# Reading records from an export (players, affiliations, organisations)
# ---------------------------------------------------------------------------


def records_from_tables(tables: dict[str, list[dict]]) -> list[Record]:
    """Records from the tables ml/detectors/features.py reads. Never `status` or `merged_into`:
    those are the record of a merge a person already made (see ml/detectors/duplicate.py)."""
    org_names = {o["id"]: o.get("name") for o in tables.get("organizations", [])}
    clubs: dict[str, set[str]] = defaultdict(set)
    for a in tables.get("affiliations", []):
        name = org_names.get(a.get("organization_id"))
        if name:
            clubs[a["player_id"]].add(name)
    out = []
    for p in tables.get("players", []):
        dob = p.get("date_of_birth")
        if isinstance(dob, str):
            dob = date.fromisoformat(dob)
        out.append(Record(
            id=p["id"], names=[n for n in (p.get("full_name"), p.get("known_as")) if n],
            sex=p.get("sex"), sport=p.get("primary_sport"), date_of_birth=dob,
            nationality=frozenset(p.get("nationality") or []), clubs=frozenset(clubs.get(p["id"], set())),
            source=p.get("source"),
        ))
    return out


# ---------------------------------------------------------------------------
# Proposals for the integrity board (ml/write_flags.py)
# ---------------------------------------------------------------------------

# Chosen on the calibration seeds (ml/run_identity_eval.py, where the reasoning is).
LINK = 0.5


def propose(tables: dict[str, list[dict]], link: float = LINK) -> tuple[list[ScoredPair], dict[str, Record]]:
    """The links to put in front of a person: within each group the engine forms, the pairs
    that scored at least `link` themselves. A pair joined only through a third record is left
    out: it has no evidence of its own to show, and merging the direct links joins it anyway.

    Records already merged into another are left out first: there is nothing left to merge.
    (Grading reads every record, as the detectors do; this is the one place status is read.)
    Returns the links, strongest first, and the records by id."""
    active = {**tables, "players": [p for p in tables.get("players", []) if p.get("status") != "merged"]}
    records = records_from_tables(active)
    scored, _ = score(records)
    return links_of(records, scored, link), {r.id: r for r in records}


def links_of(records: list[Record], scored: list[ScoredPair], link: float = LINK) -> list[ScoredPair]:
    """The direct links inside the groups `group` forms, strongest first."""
    group_of = {}
    for i, g in enumerate(group(records, scored, link)):
        for x in g:
            group_of[x] = i
    links = [s for s in scored if s.probability >= link and s.a in group_of and group_of[s.a] == group_of.get(s.b)]
    links.sort(key=lambda s: (-s.probability, *sorted((s.a, s.b))))
    return links


_SAYS = {
    ("name", "all"): "Every word after the given name matches the other record's name",
    ("name", "all-one-word"): "The one word after the given name matches the other record's name",
    ("name", "most"): "Most words after the given name match",
    ("name", "some"): "Only some words after the given name match",
    ("name", "none"): "No word after the given name matches",
    ("given", "same"): "Same given name",
    ("given", "different"): "Different given names (relatives share the rest of a name)",
    ("dob", "exact"): "Same date of birth",
    ("dob", "transposed"): "Dates of birth with the day and month swapped",
    ("dob", "near"): "Dates of birth within a week of each other",
    ("dob", "conflict"): "Dates of birth disagree",
    ("dob", "unknown"): "No date of birth on one record, so the date could not be checked",
    ("nationality", "same"): "Same nationality",
    ("nationality", "different"): "Different nationalities recorded",
    ("club", "same"): "Registered at the same club",
    ("club", "different"): "Registered at different clubs",
}


def _script(record: Record) -> str:
    text = " ".join(record.names)
    return "Arabic" if any(names._is_arabic(w) for w in text.split()) else "Latin"


def evidence(pair: ScoredPair, a: Record, b: Record) -> list[str]:
    """What the pair agreed and disagreed on, in words, for the reviewer."""
    points = []
    if _script(a) != _script(b):
        points.append("One name is written in Arabic and the other in Latin letters; they were matched by sound")
    for f in ("name", "given", "dob", "nationality", "club"):
        said = _SAYS.get((f, pair.levels.get(f)))
        if said:
            points.append(said)
    return points
