"""Age ranges in plain words, read by rule, for scout search and the assistant.

"Under 16" has to mean the same thing everywhere a person can type it. Each rule turns a
phrase into whole years, `(from, to)`, both ends included and either end open (None):

    under 16, U16, U-16, تحت ١٦     ->  (None, 15)
    16 and under                    ->  (None, 16)
    16+, 16 and over                ->  (16, None)
    over 16, older than 16          ->  (17, None)
    فوق ١٨  (Egyptian usage)         ->  (18, None)
    aged 15, 15 year olds, ١٥ سنة   ->  (15, 15)
    14 to 16, between 14 and 16     ->  (14, 16)
    adults, seniors, كبار            ->  (18, None)

Arabic digits are read as digits. The first rule that matches wins, so ranges come before the
single ages they contain. A number of three digits is never an age, so "over 180cm" is left
for the height filter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_N = r"(\d{1,2})(?!\d)"

_RULES: list[tuple[re.Pattern, object]] = [
    (re.compile(rf"\bbetween\s*{_N}\s*(?:and|&)\s*{_N}", re.I), lambda a, b: (int(a), int(b))),
    (re.compile(rf"(?:بين|من)\s*{_N}\s*(?:و|ل|الى|إلى)\s*{_N}"), lambda a, b: (int(a), int(b))),
    (re.compile(rf"\b{_N}\s*(?:to|-|–)\s*{_N}\b", re.I), lambda a, b: (int(a), int(b))),
    (re.compile(rf"\b{_N}\s*(?:and|or)\s*(?:under|younger|below)\b", re.I), lambda n: (None, int(n))),
    (re.compile(rf"\b{_N}\s*(?:\+|(?:and|or)\s*(?:over|older|above|up)\b)", re.I), lambda n: (int(n), None)),
    (re.compile(rf"\b(?:under|below|younger\s+than)[\s-]*{_N}", re.I), lambda n: (None, int(n) - 1)),
    (re.compile(rf"\bu-?{_N}s?\b", re.I), lambda n: (None, int(n) - 1)),
    (re.compile(rf"(?:تحت|أقل من|اقل من)\s*{_N}"), lambda n: (None, int(n) - 1)),
    (re.compile(rf"\b(?:over|older\s+than|above)\s*{_N}", re.I), lambda n: (int(n) + 1, None)),
    # In Egyptian Arabic "فوق ١٨" is said for "eighteen and up".
    (re.compile(rf"(?:فوق|أكبر من|اكبر من)\s*{_N}"), lambda n: (int(n), None)),
    (re.compile(rf"\b(?:aged|age)\s*{_N}\b", re.I), lambda n: (int(n), int(n))),
    (re.compile(rf"\b{_N}[\s-]*(?:years?|yrs?)[\s-]*olds?\b", re.I), lambda n: (int(n), int(n))),
    (re.compile(rf"\b{_N}\s*(?:سنة|سنين|سنه)"), lambda n: (int(n), int(n))),
    (re.compile(r"\b(?:adults?|seniors?|grown[\s-]?ups?)\b|كبار", re.I), lambda: (18, None)),
]


@dataclass(frozen=True)
class AgeMatch:
    age_from: int | None
    age_to: int | None
    # Where in the text the phrase was, so a caller can take it out of what is left to read.
    start: int
    end: int


def find(text: str) -> AgeMatch | None:
    """The first age range named in `text`, or None."""
    # One character for one, so positions in the translated text are positions in `text`.
    plain = text.translate(_ARABIC_DIGITS)
    for pattern, make in _RULES:
        if match := pattern.search(plain):
            age_from, age_to = make(*match.groups())
            if age_from is not None and age_to is not None and age_from > age_to:
                age_from, age_to = age_to, age_from
            return AgeMatch(age_from, age_to, match.start(), match.end())
    return None


def words(age_from: int | None, age_to: int | None) -> str:
    """The range in words, the same way for every phrasing: "under 15", "16 and over"."""
    if age_from is None and age_to is None:
        return "any age"
    if age_from is None:
        return f"under {age_to + 1}"
    if age_to is None:
        return f"{age_from} and over"
    if age_from == age_to:
        return f"{age_from}"
    return f"{age_from} to {age_to}"
