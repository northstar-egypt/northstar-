"""Duplicate identity detector, v1.

The same human entered twice. In this dataset the second record differs by some
combination of Arabic orthography, a dropped grandfather's name, a date of birth
off by a few days, a transposed day and month, and a different external id. Every
one of those is a real way a second clerk creates a second record for a player
who is already in the system.

Approach: block, then score pairs
---------------------------------
Comparing all 212 players to each other is 22,366 pairs, which is nothing here but
is 50 billion at national scale, so the shape is built for the scale it will need.
Candidates are blocked on sex, sport and a date-of-birth window before any name
comparison happens, and only surviving pairs are scored.

What it deliberately does not look at
-------------------------------------
`status` and `merged_into`. Six of the twelve planted clusters are already
resolved, and a resolved cluster carries `status="merged"` and a `merged_into`
pointer straight to its twin. Reading those fields would score near perfectly on
half the answer key while detecting nothing at all, because they are the record of
a merge a human already performed. The harness includes exactly that as a
baseline, named `leakage_merged_into`, so the gap between it and a real detector
is visible rather than accidental.

Name matching
-------------
Names are normalised with the standard Arabic equivalences: alef forms collapse,
teh marbuta to heh, alef maqsura and yeh collapse, hamza carriers reduce to their
base, and diacritics and tatweel are stripped. Comparison is then token
containment rather than whole-string equality, because Egyptian names carry the
father's and grandfather's names and the commonest duplicate is one clerk typing
four parts where another typed two. Containment treats "Ahmed Mohamed Ali" and
"Ahmed Ali" as a strong match, which is the behaviour wanted, while plain Jaccard
would score it 0.67 and rank it below a worse match.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from .features import FeatureSet, PlayerFeatures

# Collapses the orthographic variants that make one Arabic name two strings.
_ARABIC_EQUIVALENCES = {
    "أ": "ا",
    "إ": "ا",
    "آ": "ا",
    "ٱ": "ا",
    "ة": "ه",
    "ى": "ي",
    "ئ": "ي",
    "ؤ": "و",
}
# Harakat (short vowel marks) and tatweel, which are decorative and inconsistently typed.
_ARABIC_STRIP = re.compile(r"[ـً-ٰٟ]")


def normalise_name(name: str) -> str:
    """Canonical form of an Arabic or Latin name for comparison purposes."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", name)
    text = _ARABIC_STRIP.sub("", text)
    text = "".join(_ARABIC_EQUIVALENCES.get(ch, ch) for ch in text)
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def name_tokens(name: str) -> list[str]:
    return [t for t in normalise_name(name).split(" ") if t]


def token_containment(a: list[str], b: list[str]) -> float:
    """Overlap as a fraction of the shorter name.

    1.0 when every part of the shorter name appears in the longer one, which is
    what a dropped middle name looks like.
    """
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / min(len(sa), len(sb))


def dob_relation(a: date | None, b: date | None, window_days: int) -> str | None:
    """How two dates of birth relate, or None when they cannot be the same person.

    Returns one of "exact", "within_days", "day_month_transposed".
    """
    if a is None or b is None:
        return None
    if a == b:
        return "exact"
    if abs((a - b).days) <= window_days:
        return "within_days"
    # The classic re-entry error: 03/07 typed as 07/03.
    try:
        if a.replace(day=a.month, month=a.day) == b:
            return "day_month_transposed"
    except ValueError:
        pass
    try:
        if b.replace(day=b.month, month=b.day) == a:
            return "day_month_transposed"
    except ValueError:
        pass
    return None


@dataclass(frozen=True)
class DuplicateParams:
    # Days apart two recorded dates of birth may be and still be one person. The
    # generator shifts by 1 to 4 days; the window is a little wider so the rule is
    # not fitted to that exact choice.
    dob_window_days: int = 7

    # Minimum share of the shorter name that must appear in the longer one.
    min_containment: float = 0.99

    # A pair whose dates of birth are merely close, rather than identical or
    # transposed, needs the names to match outright. Two 14-year-olds born four
    # days apart at the same club is ordinary; two with the same name is not.
    min_containment_loose_dob: float = 0.99

    # Blocking on the birth year keeps the candidate set small. Widened by one so
    # a transposed day and month, which can move the date across a year boundary,
    # still meets its twin.
    year_block_slack: int = 1


def _birth_year(pf: PlayerFeatures) -> int | None:
    dob = pf.date_of_birth
    return dob.year if dob else None


def candidate_pairs(
    features: FeatureSet, params: DuplicateParams
) -> list[tuple[PlayerFeatures, PlayerFeatures]]:
    """Blocked candidate pairs, before any name comparison."""
    blocks: dict[tuple, list[PlayerFeatures]] = defaultdict(list)
    for pf in features.players.values():
        year = _birth_year(pf)
        if year is None:
            continue
        sport = pf.player.get("primary_sport")
        for offset in range(-params.year_block_slack, params.year_block_slack + 1):
            blocks[(pf.sex, sport, year + offset)].append(pf)

    seen: set[tuple[str, str]] = set()
    pairs: list[tuple[PlayerFeatures, PlayerFeatures]] = []
    for members in blocks.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                key = tuple(sorted((a.player_id, b.player_id)))
                if key in seen:
                    continue
                seen.add(key)
                pairs.append((a, b))
    return pairs


def score_pair(
    a: PlayerFeatures, b: PlayerFeatures, params: DuplicateParams
) -> tuple[bool, str]:
    """Decide whether two records are the same human, and say why."""
    relation = dob_relation(a.date_of_birth, b.date_of_birth, params.dob_window_days)
    if relation is None:
        return False, ""

    containment = token_containment(name_tokens(a.full_name), name_tokens(b.full_name))
    threshold = (
        params.min_containment_loose_dob
        if relation == "within_days"
        else params.min_containment
    )
    if containment < threshold:
        return False, ""

    detail = {
        "exact": "the same recorded date of birth",
        "within_days": "recorded dates of birth a few days apart",
        "day_month_transposed": "a date of birth with the day and month transposed",
    }[relation]
    return True, (
        f"Name matches after normalising Arabic spelling (containment "
        f"{containment:.2f}) and {detail}. Likely the same player entered twice."
    )


def detect_pairs(
    features: FeatureSet, params: DuplicateParams | None = None
) -> dict[tuple[str, str], str]:
    """Return {(id_a, id_b): reason} for every pair judged to be one person."""
    params = params or DuplicateParams()
    matches: dict[tuple[str, str], str] = {}
    for a, b in candidate_pairs(features, params):
        matched, reason = score_pair(a, b, params)
        if matched:
            matches[tuple(sorted((a.player_id, b.player_id)))] = reason
    return matches


def detect(features: FeatureSet, params: DuplicateParams | None = None) -> dict[str, str]:
    """Player-level view: every record that belongs to a matched pair.

    This is the shape `ground_truth.labels["duplicate"]` is in, which lists both
    the original and the clone.
    """
    flagged: dict[str, str] = {}
    for (a, b), reason in detect_pairs(features, params).items():
        flagged[a] = reason
        flagged[b] = reason
    return flagged
