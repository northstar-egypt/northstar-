"""Reading a scout's words as something the platform can compute.

A scout types "small for his age but scoring well". The keyword parser (services/search.py)
handles what maps cleanly onto a column: ages, heights, positions, tiers. This module handles
the rest of the sentence. It does NOT search players by meaning. It picks, for each phrase,
at most one item from a fixed list of things the platform actually computes, and the search
then filters on that computation. The chip under the box says which item a phrase was read
as, so a wrong reading is visible and the scout can rephrase.

The fixed list
--------------
- Body, from the same percentiles the profile shows (services/cohort.py): small for age
  (bottom quarter of height), tall for age (top quarter), fast (best quarter of 10 m sprint),
  each against players of the same age and gender.
- Late bloomer: an open late-bloomer flag.
- Every derived statistic a sport module marks searchable (packages/shared/sports, the
  `search` block): goals per 90, shot conversion and pass completion for football; matches
  won, service winners per set and unforced errors per set for table tennis. A new sport
  brings its own by config, not code.
- Asks the platform has no data for (preferred foot, strength, character...). Recognising
  these matters as much as the rest: read as a name, "left footed" would return nobody; read
  as "no data", it changes nothing and says so.

How a phrase is read
--------------------
A multilingual sentence-embedding model (paraphrase-multilingual-MiniLM-L12-v2, run locally
with fastembed on ONNX, no PyTorch) embeds the phrase and every item's descriptions. The
closest item wins if its cosine similarity is at least `THRESHOLD`; otherwise the phrase is
not a concept, and its words go on to the no-data word list and then to name search. The
threshold was chosen on half of a labelled phrase set and is reported on the other half,
against a keyword baseline: apps/api/tests/test_concepts.py.

The model is optional at runtime. Without it (not installed, or not downloaded) the search
falls back to the keyword behaviour and `available()` says so.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass

from app import sports

logger = logging.getLogger(__name__)

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# A word in the search box: Latin (an apostrophe may sit inside one, as in Sa'ad) or Arabic.
WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*|[ء-ي]+")
# Cosine similarity needed to read a phrase as an item. Chosen on the "tune" half of
# tests/search_phrases.py; see tests/test_concepts.py.
THRESHOLD = 0.60


@dataclass(frozen=True)
class Concept:
    id: str
    # What the chip says the phrase was read as.
    label: str
    # height_low | height_high | sprint_fast | flag | stat | no_data
    kind: str
    describe: tuple[str, ...]
    # Single words that mean this on their own, checked before the model.
    keywords: tuple[str, ...] = ()
    # For kind "stat": the derived statistic, the sports that define it, and which way is
    # better. For kind "flag": the flag type.
    key: str | None = None
    sports: tuple[str, ...] = ()
    better: str | None = None

    @property
    def answerable(self) -> bool:
        return self.kind != "no_data"


CORE: tuple[Concept, ...] = (
    Concept(
        "small_for_age",
        "height: bottom quarter for age and gender",
        "height_low",
        (
            "short compared with children of the same age",
            "below the usual height for his age group",
            "physically smaller than his peers",
            "لاعب قصير مقارنة بزملائه في نفس السن",
        ),
        ("small", "short", "undersized", "tiny", "قصير", "صغير"),
    ),
    Concept(
        "tall_for_age",
        "height: top quarter for age and gender",
        "height_high",
        (
            "taller than other children of the same age",
            "above the usual height for his age group",
            "physically tall and big for his age",
            "لاعب طويل مقارنة بزملائه في نفس السن",
        ),
        # Not "height": it is neutral, and "below average height" is not a request for tall
        # players. The held-out phrases caught it.
        ("tall", "big", "طويل"),
    ),
    Concept(
        "fast",
        "10m sprint: fastest quarter for age and gender",
        "sprint_fast",
        (
            "runs very fast",
            "quick sprint speed",
            "has a lot of pace",
            "لاعب سريع جدا في الجري",
        ),
        ("fast", "quick", "pace", "pacey", "speed", "rapid", "سريع", "سرعة"),
    ),
    Concept(
        "late_bloomer",
        "flag: late bloomer",
        "flag",
        (
            "matures later than other children",
            "his growth spurt has not come yet",
            "a late developer who will catch up physically",
            "نموه متأخر عن زملائه",
        ),
        ("late", "bloomer", "متأخر"),
        key="late_bloomer",
    ),
)

# Asks with no data behind them. The keywords include the search's earlier "no data" word
# list, so nothing it recognised is lost.
NO_DATA: tuple[Concept, ...] = tuple(
    Concept(f"no_data:{cid}", f"{label}: no data", "no_data", describe, keywords)
    for cid, label, describe, keywords in (
        ("preferred_foot", "preferred foot",
         ("which foot he prefers, left footed or right footed", "القدم المفضلة"),
         ("footed", "foot", "lefty", "righty", "بالشمال")),
        ("strength", "strength",
         ("physically strong and powerful", "قوة بدنية"),
         ("strong", "strength", "قوي")),
        ("aerial", "aerial ability",
         ("good at heading the ball and winning aerial duels", "الضربات الرأسية"),
         ("header", "air")),
        ("character", "character",
         ("good attitude, character, work rate and leadership", "أخلاق وشخصية اللاعب"),
         ("attitude", "working", "leader", "character", "brave", "pressure", "أخلاقه")),
        ("potential", "potential rating",
         ("high potential, could become a star in the future", "موهبة واعدة"),
         ("potential", "star")),
        ("technique", "technical skill",
         ("dribbling, first touch, vision and technical skill", "مهارات فنية ومراوغة"),
         ("dribbler", "vision", "touch")),
        ("advanced_stats", "expected goals",
         ("expected goals xG and advanced shooting data", "الأهداف المتوقعة"),
         ("xg",)),
        ("assists", "assists per 90", (), ("assists",)),
        ("percentile", "percentile filters", (), ("percentile",)),
        ("breakout", "breakout flag", (), ("breakout",)),
        ("similar", "similarity search", (), ("similar",)),
        ("injuries", "injury history",
         ("injury history and fitness record", "تاريخ الإصابات"),
         ("injury",)),
    )
)

# Words that carry no meaning of their own in a scout's phrase ("small for HIS AGE", "a BIT
# fast"). Dropped after keywords are taken, so they are neither read by the model nor
# searched for as names.
FILLER = frozenset(
    """a an the and or but with who that for of in at on to his her he she is are be very
    really quite bit lot lots good well player players kid kids boy boys lad age than other
    more most much over also has have one someone plenty great real
    في على من مع هو اللي ده دي جدا كتير لاعب""".split()
)


def stat_concepts(modules: dict | None = None) -> tuple[Concept, ...]:
    """One concept per searchable derived statistic, across every sport module."""
    found: dict[str, dict] = {}
    for module in (modules or sports.registry()).values():
        for period in module.periods.values():
            for stat in period.derived:
                search = stat.get("search")
                if not search:
                    continue
                entry = found.setdefault(
                    stat["key"],
                    {
                        "label": stat["label"],
                        "better": search["better"],
                        "describe": [],
                        "keywords": [],
                        "sports": [],
                    },
                )
                for field_name in ("describe", "keywords"):
                    entry[field_name] += [
                        d for d in search.get(field_name, []) if d not in entry[field_name]
                    ]
                if module.sport not in entry["sports"]:
                    entry["sports"].append(module.sport)
    return tuple(
        Concept(
            key,
            f"{e['label'].lower()}: {'top' if e['better'] == 'higher' else 'best'} quarter of their sport and tier",
            "stat",
            tuple(e["describe"]),
            tuple(e["keywords"]),
            key=key,
            sports=tuple(e["sports"]),
            better=e["better"],
        )
        for key, e in found.items()
    )


def all_concepts() -> tuple[Concept, ...]:
    return CORE + stat_concepts() + NO_DATA


@dataclass
class Reading:
    """What one phrase was read as.

    A phrase is either a concept phrase or a name phrase, never both: in "physically small",
    "physically" is part of how the scout said it, and searching for a player called
    Physically would return nobody while the chip claimed to have helped. So:

      concepts   what it was read as, each with how ("keyword" or "model") and from what
      unused     words of a concept phrase that the reading did not need; they change
                 nothing, and the screen says so
      leftover   the words of a name phrase, for name search
    """

    concepts: list[tuple[Concept, str, str]]
    leftover: list[str]
    unused: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.unused is None:
            self.unused = []


def read(words: list[str], reader: Reader | None = None) -> Reading:
    """Read one phrase, already split into words, the way the search box does.

    1. A word that is a keyword is that concept, on its own.
    2. Filler words ("for his age") are dropped.
    3. No keyword, and two or more words left: the model reads them together; at or above
       `THRESHOLD` they are that concept. One word is never given to the model: on a single
       short word, and on names above all, it is unreliable (tests/test_concepts.py), and a
       single unknown word is most often a name.
    4. A phrase read as a concept reports its other words as `unused`. A phrase that is not
       returns them as `leftover`, for name search.
    """
    concepts = all_concepts()
    by_keyword = {}
    for concept in concepts:
        for keyword in concept.keywords:
            by_keyword.setdefault(keyword, concept)
    found: list[tuple[Concept, str, str]] = []
    rest: list[str] = []
    for word in words:
        concept = by_keyword.get(word.lower())
        if concept is not None:
            if all(c.id != concept.id for c, _, _ in found):
                found.append((concept, "keyword", word))
        elif word.lower() not in FILLER:
            rest.append(word)
    if found:
        return Reading(found, [], rest)
    if len(rest) >= 2 and reader is not None:
        concept, _ = reader.read(" ".join(rest))
        if concept is not None:
            return Reading([(concept, "model", " ".join(rest))], [])
    return Reading([], rest)


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


def _cache_dir() -> str | None:
    return os.environ.get("NORTHSTAR_MODELS_DIR") or None


class Reader:
    """Embeds phrases and picks the closest concept. One per process, built lazily."""

    def __init__(self, embed, concepts: tuple[Concept, ...]):
        import numpy as np

        self._np = np
        self._embed = embed
        self.concepts = concepts
        owners, texts = [], []
        for concept in concepts:
            for text in concept.describe:  # keyword-only items have none
                owners.append(concept)
                texts.append(text)
        self._owners = owners
        self._matrix = self._vectors(texts)

    def _vectors(self, texts: list[str]):
        vectors = self._np.asarray(list(self._embed(texts)), dtype=float)
        return vectors / self._np.linalg.norm(vectors, axis=1, keepdims=True)

    def scores(self, phrase: str) -> dict[str, float]:
        """Best cosine similarity per concept id."""
        similarities = self._matrix @ self._vectors([phrase])[0]
        best: dict[str, float] = {}
        for owner, value in zip(self._owners, similarities):
            best[owner.id] = max(best.get(owner.id, -1.0), float(value))
        return best

    def read(self, phrase: str, threshold: float = THRESHOLD) -> tuple[Concept | None, float]:
        scores = self.scores(phrase)
        cid = max(scores, key=scores.get)
        score = scores[cid]
        if score < threshold:
            return None, score
        return next(c for c in self.concepts if c.id == cid), score


_reader: Reader | None = None
_failed = False
_lock = threading.Lock()


def get_reader() -> Reader | None:
    """The shared reader, or None when the model cannot be loaded (then search falls back to
    keywords). The first call loads the model, about a second from a warm cache."""
    global _reader, _failed
    with _lock:
        if _reader is None and not _failed:
            try:
                from fastembed import TextEmbedding

                model = TextEmbedding(MODEL_NAME, cache_dir=_cache_dir())
                _reader = Reader(model.embed, all_concepts())
            except Exception:  # noqa: BLE001
                _failed = True
                logger.exception("Concept search is off: the embedding model did not load.")
        return _reader


def available() -> bool:
    return get_reader() is not None


def warm_up() -> None:
    """Load the model in the background when the API starts."""
    threading.Thread(target=get_reader, daemon=True).start()
