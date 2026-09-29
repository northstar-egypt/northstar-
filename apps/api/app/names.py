"""Name matching across Arabic script and Latin spellings.

Why this exists
---------------
Players' names reach the platform in two scripts. Academy and federation records are in
Arabic (محمد صلاح). FootyStats, and the European sources for the diaspora tier, spell the
same names in Latin, and not consistently: Mohamed, Mohammed, Muhammad and Mohamad are all
one name. A scout types whichever they know. Comparing letters finds none of these across
the gap; before this module the search found nothing for a Latin name and silently ignored an
Arabic one.

How it matches
--------------
Arabic does not write short vowels, and Latin spellings of Arabic names differ mostly in
their vowels. So both sides are read as consonant sounds, with vowels treated the way each
script actually uses them:

- Consonants fold into sound classes both scripts share: ش, sh and French ch are one; خ and
  kh; ج, g and j (Egyptian Gamal, Levantine Jamal); ق, k and q; ث, t and th; د ذ ض, d and dh.
  A doubled letter counts once.
- A **long vowel written in Arabic** (ا و ي, and ى) must be spelled by a Latin vowel that can
  spell it: ي by i, e or y; و by o, u or w; ا by a. This is why "Hassan" does not find
  حسين: its a cannot spell ي. The other way round it cannot help: "Hussein" still finds حسن,
  because nothing in حسن rules out the Latin vowels, which are read as short ones.
- A **Latin vowel with no Arabic long vowel under it** is a short vowel, unwritten in Arabic,
  and is skipped.
- ع and hamza inside a word are written in Latin as a vowel, an apostrophe or nothing (Saad,
  Sa'ad, Shaaban), so they may match a vowel or nothing. A final ة is not written as a
  consonant in Latin (Fatma), and a final h after a vowel may be silent (Fatmah, Abdalla).
- An Arabic word that starts with a vowel (أ إ آ, or ع) must start with one in Latin.
- The article (ال, El-, Al-, glued or not) is ignored, and عبد with the word after it is one
  name however it is spelled: Abdelrahman, Abdel Rahman, Abdulrahman, Abd El-Rahman.

Latin against Latin compares the consonant sounds only, so Mohamed matches Muhammad. Arabic
against Arabic compares letters after the usual normalisation (أ إ آ to ا, ة to ه, ى to ي,
diacritics removed), so احمد typed without the hamza still finds أحمد.

A query matches a player when **every** word of it matches some word of their name or
known-as name, so "Ahmed Hassan" does not return every Ahmed.

How well it works
-----------------
Scored on real-world spellings of every name the synthetic generator uses, half of them held
out while the rules were written: apps/api/tests/test_names.py prints the numbers and fails
if they drop. On the held-out half: every one of 117 spellings finds its name, and 0.21% of
checks against a different name match it. Latin against Latin, 0.26%. In a search that
means nothing is missed, but 71% of the players returned are the right ones: the names that
collide are common, so one collision returns many players. Names that share their
consonants and differ only in vowels (Said and El-Sayed, Omar and Amr, Salah and Saleh) are
listed there, not hidden. There is no tolerance for a wrong consonant, so a typo like
"Mohamef" finds nothing.

Standard library only.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# A word is read into a tuple of units:
#   ("c", sound)       a consonant sound class
#   ("v", letters)     Latin: a run of vowel letters
#   ("h?",)            Latin: a final h after a vowel, which may be silent
#   ("long", allowed)  Arabic: a written long vowel; a Latin vowel in `allowed` must spell it
#   ("opt",)           Arabic: ع or hamza inside a word; a Latin vowel run, or nothing
#   ("opt-h",)         Arabic: a final ه; a Latin h, or nothing
#   ("opt-l",)         Arabic: the l of an article inside عبد ال...; a Latin l, or nothing
#   ("start", allowed) Arabic: the word starts with a vowel (allowed None: any vowel)

_LATIN_VOWELS = frozenset("aeiou")
_LATIN_DIGRAPHS = {"sh": "S", "ch": "S", "kh": "x", "gh": "g", "th": "t", "dh": "d", "ph": "f"}
_LATIN_SOUNDS = {
    "b": "b", "p": "b", "c": "k", "d": "d", "f": "f", "v": "f", "g": "g", "j": "g",
    "h": "h", "k": "k", "q": "k", "l": "l", "m": "m", "n": "n", "r": "r", "s": "s",
    "t": "t", "z": "z", "x": "ks", "w": "w", "y": "y",
}
_LATIN_ARTICLES = {"el", "al", "ul"}
_LATIN_ABD = {"abd", "abdel", "abdul", "abdal", "abdu", "abdoul"}
# Abd glued to the next name, with the connector it is written with: Abdelaziz, Abdulaziz.
_ABD_GLUED = re.compile(r"^abd(?:el|al|ul|ol|il)?(?=[a-z]{2})")
_GLUED_ARTICLE = re.compile(r"^(?:el|al)(?=[a-z]{3})")

_ARABIC_SOUNDS = {
    "ب": "b", "ت": "t", "ث": "t", "ج": "g", "ح": "h", "خ": "x", "د": "d", "ذ": "d",
    "ر": "r", "ز": "z", "س": "s", "ش": "S", "ص": "s", "ض": "d", "ط": "t", "ظ": "z",
    "غ": "g", "ف": "f", "ق": "k", "ك": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h",
}
_ALEFS = "اأإآ"
_HAMZAS = "ءؤئ"
_LONG = {"ا": frozenset("a"), "ى": frozenset("a"), "و": frozenset("ouw"), "ي": frozenset("iey")}
_DIACRITICS = re.compile("[ً-ٰٟـ]")
_ARABIC_WORD = re.compile("[ء-يً-ٰٟـ]+")


# ---------------------------------------------------------------------------
# Splitting a name into words
# ---------------------------------------------------------------------------


def _latin_words(text: str) -> list[str]:
    """Lowercased, accents and apostrophes gone, articles dropped, Abd joined to the next."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"['’`]", "", text)
    out: list[str] = []
    joining = False
    for word in re.findall(r"[a-z]+", text):
        if word in _LATIN_ARTICLES:
            continue
        if joining:
            out[-1] += word
            joining = False
        elif word in _LATIN_ABD:
            out.append("abd")
            joining = True
        else:
            out.append(word)
    return out


def _arabic_words(text: str) -> list[str]:
    """Diacritics gone, عبد joined to the next word with a space."""
    out: list[str] = []
    joining = False
    for word in _ARABIC_WORD.findall(text):
        word = _DIACRITICS.sub("", word)
        if joining:
            out[-1] += " " + word
            joining = False
        elif word == "عبد":
            out.append(word)
            joining = True
        else:
            out.append(word)
    return out


def words(text: str) -> list[str]:
    """The name words in `text`, in both scripts, as the matcher reads them."""
    return _arabic_words(text) + _latin_words(text)


# ---------------------------------------------------------------------------
# Reading a word into units
# ---------------------------------------------------------------------------


@lru_cache(maxsize=65536)
def _latin_units(word: str) -> tuple[tuple, ...]:
    glued = _ABD_GLUED.match(word)
    if glued:
        # Read the two halves apart: "abd" + "hamid" must not become the digraph "dh".
        return _latin_units("abd") + _latin_units(word[glued.end() :])
    units: list[tuple] = []
    i = 0
    while i < len(word):
        ch = word[i]
        if word[i : i + 2] in _LATIN_DIGRAPHS:
            sound = _LATIN_DIGRAPHS[word[i : i + 2]]
            i += 2
        elif ch in _LATIN_VOWELS or (ch in "yw" and i > 0 and units and units[-1][0] == "v"):
            # A vowel run. A y or w straight after a vowel belongs to it (Sayed, Awad), where
            # an Arabic ي or و can use it.
            run = ""
            while i < len(word) and (word[i] in _LATIN_VOWELS or (word[i] in "yw" and run)):
                run += word[i]
                i += 1
            units.append(("v", run))
            continue
        elif ch in "yw" and i > 0:
            units.append(("v", ch))  # a y or w after a consonant: Rushdy, Marwan
            i += 1
            continue
        else:
            sound = _LATIN_SOUNDS.get(ch, "")
            i += 1
        for part in sound:
            if not (units and units[-1] == ("c", part)):  # a doubled letter is one sound
                units.append(("c", part))
    # Merge vowel runs that ended up adjacent (Marwan: "w" then "a").
    merged: list[tuple] = []
    for unit in units:
        if merged and unit[0] == "v" and merged[-1][0] == "v":
            merged[-1] = ("v", merged[-1][1] + unit[1])
        else:
            merged.append(unit)
    if len(merged) >= 2 and merged[-1] == ("c", "h") and merged[-2][0] == "v":
        merged[-1] = ("h?",)
    return tuple(merged)


def _latin_readings(word: str) -> list[tuple[tuple, ...]]:
    """A glued article (Elsayed) is read both ways, because Elias and Alia are not articles."""
    readings = [_latin_units(word)]
    if not _ABD_GLUED.match(word) and _GLUED_ARTICLE.match(word):
        readings.append(_latin_units(word[2:]))
    return readings


@lru_cache(maxsize=65536)
def _arabic_units(word: str) -> tuple[tuple, ...]:
    units: list[tuple] = []
    for index, part in enumerate(word.split(" ")):
        if part.startswith("ال") and len(part) > 3:
            part = part[2:]
            if index > 0:
                units.append(("opt-l",))  # عبد الرحمن: Abdelrahman or Abdrahman
        units.extend(_arabic_part(part, word_start=(index == 0)))
    return tuple(units)


def _arabic_part(part: str, word_start: bool) -> list[tuple]:
    units: list[tuple] = []
    letters = list(part)
    i = 0
    if letters and (letters[0] in _ALEFS or letters[0] in _HAMZAS or letters[0] == "ع"):
        first, after = letters[0], letters[1] if len(letters) > 1 else ""
        if not word_start:
            units.append(("opt",))  # عبد العزيز: the vowel after Abd may be written or not
            i = 1
        elif first == "آ":
            units.append(("start", frozenset("a")))
            i = 1
        elif after in "يو" and after and len(letters) > 2:
            units.append(("start", _LONG[after] | frozenset("a")))  # إيمان, أيمن
            i = 2
        elif after == "ا":
            units.append(("start", frozenset("a")))  # عادل
            i = 2
        else:
            units.append(("start", None))
            i = 1
    elif letters and letters[0] in "وي":
        units.append(("c", "w" if letters[0] == "و" else "y"))
        i = 1
    while i < len(letters):
        ch = letters[i]
        at_end = i == len(letters) - 1
        if ch in _ALEFS or ch == "ى":
            units.append(("long", _LONG["ا"]))
        elif ch in "وي":
            if ch == "و" and at_end and letters[i - 1] not in "اوي":
                units.append(("opt",))  # عمرو: Amr or Amro
            else:
                units.append(("long", _LONG[ch]))
        elif ch == "ع" or ch in _HAMZAS:
            units.append(("opt",))
        elif ch == "ة":
            pass
        elif ch == "ه" and at_end:
            units.append(("opt-h",))  # الله: Abdallah or Abdalla
        elif ch in _ARABIC_SOUNDS:
            sound = _ARABIC_SOUNDS[ch]
            if not (units and units[-1] == ("c", sound)):
                units.append(("c", sound))
        i += 1
    return units


# ---------------------------------------------------------------------------
# Comparing
# ---------------------------------------------------------------------------


def _arabic_spelled_by(a: tuple, l: tuple) -> bool:
    """Can the Latin units `l` be a spelling of the Arabic units `a`?"""

    @lru_cache(maxsize=None)
    def go(i: int, j: int) -> bool:
        latin = l[j] if j < len(l) else None
        if i == len(a):
            return all(u[0] in ("v", "h?") for u in l[j:])
        kind = a[i][0]
        if kind == "start":
            if j != 0 or latin is None or latin[0] != "v":
                return False
            allowed = a[i][1]
            if allowed is not None and not set(latin[1]) & allowed:
                return False
            return go(i + 1, j + 1) or vowels_in_run(i + 1, j)
        if kind in ("opt", "opt-h", "opt-l"):
            if go(i + 1, j):
                return True
            if latin is None:
                return False
            if kind == "opt":
                return latin[0] == "v" and (go(i + 1, j + 1) or vowels_in_run(i + 1, j))
            if kind == "opt-h":
                return latin in (("c", "h"), ("h?",)) and go(i + 1, j + 1)
            return latin == ("c", "l") and go(i + 1, j + 1)
        if kind == "long":
            return latin is not None and latin[0] == "v" and vowels_in_run(i, j)
        # A consonant.
        if latin is None:
            return False
        if latin[0] == "v":
            return go(i, j + 1)  # a short vowel, which Arabic does not write
        if latin == ("h?",):
            return a[i] == ("c", "h") and go(i + 1, j + 1)
        return latin == a[i] and go(i + 1, j + 1)

    def vowels_in_run(i: int, j: int) -> bool:
        """The Arabic vowel units from i on, all spelled inside the one Latin run at j."""
        run, pos, k = l[j][1], 0, i
        while k < len(a) and a[k][0] in ("long", "opt"):
            if a[k][0] == "long":
                while pos < len(run) and run[pos] not in a[k][1]:
                    pos += 1
                if pos == len(run):
                    return False
                pos += 1
            k += 1
        return go(k, j + 1)

    return go(0, 0)


def _latin_skeleton(units: tuple) -> str:
    out = ["V"] if units and units[0][0] == "v" else []
    out += [u[1] for u in units if u[0] == "c"]
    return "".join(out)


def _normalise_arabic(word: str) -> str:
    word = word.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"}))
    return " ".join(p[2:] if p.startswith("ال") and len(p) > 3 else p for p in word.split(" "))


def _is_arabic(word: str) -> bool:
    return bool(_ARABIC_WORD.match(word))


def word_matches(query_word: str, name_word: str) -> bool:
    """One word against one word, in whichever scripts they are in."""
    query_arabic, name_arabic = _is_arabic(query_word), _is_arabic(name_word)
    if query_arabic and name_arabic:
        return _normalise_arabic(query_word) == _normalise_arabic(name_word)
    if not query_arabic and not name_arabic:
        return any(
            _latin_skeleton(q) == _latin_skeleton(n) != ""
            for q in _latin_readings(query_word)
            for n in _latin_readings(name_word)
        )
    arabic, latin = (query_word, name_word) if query_arabic else (name_word, query_word)
    units = _arabic_units(arabic)
    return any(_arabic_spelled_by(units, reading) for reading in _latin_readings(latin))


def matches(query: str, *names: str | None) -> bool:
    """True when every word of `query` matches some word of one of `names` (the full name and
    the known-as name, say). A query with no name words in it matches nothing."""
    query_words = words(query)
    if not query_words:
        return False
    name_words = [w for name in names if name for w in words(name)]
    return all(any(word_matches(q, n) for n in name_words) for q in query_words)
