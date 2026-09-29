"""Baselines every detector has to beat.

A precision/recall/F1 number means nothing on its own. On a set where 6.6% of
players are late bloomers, flagging everybody scores a recall of 1.0 and an F1 of
0.12, and flagging nobody scores an F1 of 0.0 while being right about 93% of the
population. Neither is a detector. The only way to read a score is next to what a
trivial rule achieves on the same data, which is why the harness prints these in
the same table rather than in an appendix nobody opens.

Three are generic and apply to any detector. The rest are the specific cheap
tricks that would look like success for one detector in particular, including one
that cheats outright.
"""

from __future__ import annotations

import random
import statistics

from .features import FeatureSet

# ---------------------------------------------------------------------------
# Generic
# ---------------------------------------------------------------------------


def all_positive(features: FeatureSet) -> set[str]:
    """Flag everybody. Recall 1.0, precision equal to the prevalence."""
    return set(features.players)


def none_positive(features: FeatureSet) -> set[str]:
    """Flag nobody. The accuracy this scores is why accuracy is not reported."""
    return set()


def random_at_prevalence(features: FeatureSet, support: int, seed: int = 0) -> set[str]:
    """Flag `support` players at random.

    The honest null: a detector that finds the right number of cases but has no
    idea which ones. Expected precision and recall both equal the prevalence.
    """
    rng = random.Random(seed)
    ids = sorted(features.players)
    return set(rng.sample(ids, min(support, len(ids))))


# ---------------------------------------------------------------------------
# Late bloomer
# ---------------------------------------------------------------------------


def shortest_for_age(features: FeatureSet, support: int) -> set[str]:
    """The `support` players furthest below the median height for their age.

    This is what a coach does by eye, and it is the thing the project claims to
    improve on. If the detector cannot beat it, the late-bloomer story does not
    hold up.
    """
    ranked = sorted(
        (pf for pf in features.players.values() if pf.height_z_mean is not None),
        key=lambda pf: pf.height_z_mean,
    )
    return {pf.player_id for pf in ranked[:support]}


def shortest_for_birth_year(features: FeatureSet, support: int) -> set[str]:
    """Biased on purpose. A control for the relative age audit, not a detector.

    The same idea as `shortest_for_age`, but each height is compared against everyone born
    in the same calendar year rather than everyone of the same exact age. That is how
    academies group children, and it is the textbook source of the relative age effect: a
    child born in December is compared with team-mates up to a year older, looks short, and
    gets flagged. Only youth players (11 to 18.5, three or more readings) are ranked, the
    same eligibility as the late bloomer detector.

    It is in the audit so that every run shows what a biased detector looks like next to the
    real one. Pooled over 20 seeds it is caught decisively (false positive rate 0.5% for Q1
    against 3.1% for Q4, p < 0.001); if it ever stops being caught, the audit has lost its
    power and its "no difference" verdicts mean nothing.
    """
    buckets: dict[tuple[str, int], list[float]] = {}
    for pf in features.players.values():
        if pf.date_of_birth is None:
            continue
        for when, height in pf.heights:
            buckets.setdefault((pf.sex, when.year - pf.date_of_birth.year), []).append(height)
    reference = {
        key: (statistics.median(values), max(statistics.pstdev(values), 0.5))
        for key, values in buckets.items()
        if len(values) >= 5
    }

    scores: dict[str, float] = {}
    for pf in features.players.values():
        if pf.date_of_birth is None or len(pf.heights) < 3 or not 11 <= pf.stated_age <= 18.5:
            continue
        zs = []
        for when, height in pf.heights:
            entry = reference.get((pf.sex, when.year - pf.date_of_birth.year))
            if entry is not None:
                zs.append((height - entry[0]) / entry[1])
        if zs:
            scores[pf.player_id] = sum(zs) / len(zs)
    return set(sorted(scores, key=lambda pid: (scores[pid], pid))[:support])


# ---------------------------------------------------------------------------
# Fraud
# ---------------------------------------------------------------------------


def any_self_submitted(features: FeatureSet) -> set[str]:
    """Flag every player with an unvalidated self-submitted performance row.

    The obvious first idea, and a bad one: the generator gives ordinary players
    self-submitted rows too, so this mostly measures how many people filled in
    their own form.
    """
    flagged = set()
    for pf in features.players.values():
        for entry in pf.performance:
            if entry.get("source") == "self_submitted" and not entry.get("is_validated"):
                flagged.add(pf.player_id)
                break
    return flagged


# ---------------------------------------------------------------------------
# Duplicate
# ---------------------------------------------------------------------------


def exact_name_match(features: FeatureSet) -> set[str]:
    """Flag records sharing a byte-identical full name.

    No normalisation. The comparison a plain SQL GROUP BY would make, and the
    reason 85% of the planted clusters carry an orthographic variation.
    """
    by_name: dict[str, list[str]] = {}
    for pf in features.players.values():
        by_name.setdefault(pf.full_name, []).append(pf.player_id)
    return {pid for ids in by_name.values() if len(ids) > 1 for pid in ids}


def leakage_merged_into(features: FeatureSet) -> set[str]:
    """Read the answer off the record. Not a detector, a control.

    Six of the twelve planted clusters have already been resolved by a human, and
    those rows carry `status="merged"` and a `merged_into` pointer to the record
    they were folded into. A detector that reads those fields scores about half
    the answer key without doing anything, and would look respectable next to a
    real one.

    It is here so that gap is stated out loud. Any duplicate detector whose score
    sits near this one is probably reading the same thing by accident.
    """
    flagged = set()
    for pf in features.players.values():
        target = pf.player.get("merged_into")
        if target:
            flagged.add(pf.player_id)
            if target in features.players:
                flagged.add(target)
    return flagged
