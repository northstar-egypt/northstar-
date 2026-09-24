"""Fraud detector, v1.

The answer key plants two kinds of fraud under one label, and they are nothing
alike:

  age_misrepresentation                    9 of the 14 cases
      A recorded date of birth younger than the real one. The body and the season
      were generated from the true age, so the player is too big, too fast and too
      dominant for the age on the record. Hard, statistical, and the one that
      matters: this is the fraud that actually happens in youth football.

  implausible_self_reported_performance    5 of the 14 cases
      Self-submitted match rows whose numbers do not survive arithmetic. More
      goals than shots. More passes completed than attempted. A distance covered
      that no human has run. Easy, deterministic, and worth catching at the point
      of entry rather than by a model at all.

Scoring them as one number hides everything interesting, so this module exposes
the two rules separately as well as combined, and the harness reports the
breakdown. A combined F1 of 0.8 that is 5 easy cases and 6 of 9 hard ones is a
different result from 0.8 spread evenly, and only one of them is worth shipping.

The arithmetic rule is not machine learning and should not pretend to be. It is
an integrity check that belongs in ingest validation, and the fact that it scores
perfectly here is a statement about the generator, not about a model. It is
included because the answer key labels those players and recall is measured
against all 14.
"""

from __future__ import annotations

from dataclasses import dataclass

from .features import FeatureSet, PlayerFeatures

# Rows are flagged when they break arithmetic that cannot be broken. Each entry is
# (description, required metric keys, predicate).
#
# The required keys are not decoration. A rule only fires when every field it
# compares is actually present and numeric, because a missing field means unknown
# and not zero. Reading absence as zero makes "scored without playing" fire on any
# row that records a goal without recording minutes, which is an ordinary shape for
# a partial import and would have put a fraud flag on a real child's record. A test
# caught it; see `test_ordinary_rows_are_not_caught`.
IMPOSSIBLE_ROW_RULES: tuple[tuple[str, tuple[str, ...], object], ...] = (
    ("more goals than shots", ("goals", "shots"), lambda m: m["goals"] > m["shots"]),
    (
        "more shots on target than shots",
        ("shots_on_target", "shots"),
        lambda m: m["shots_on_target"] > m["shots"],
    ),
    (
        "more passes completed than attempted",
        ("passes_completed", "passes_attempted"),
        lambda m: m["passes_completed"] > m["passes_attempted"],
    ),
    # The record for distance covered in a professional match sits around 14km.
    # Anything past that in a youth fixture is a data-entry problem or a lie.
    ("distance beyond human range", ("distance_km",), lambda m: m["distance_km"] > 14.0),
    (
        "scored without playing",
        ("minutes_played", "goals"),
        lambda m: m["minutes_played"] == 0 and m["goals"] > 0,
    ),
)


def _numeric(metrics: dict, keys: tuple[str, ...]) -> dict[str, float] | None:
    """The named metrics as floats, or None when any of them is missing or not a number."""
    out: dict[str, float] = {}
    for key in keys:
        value = metrics.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        out[key] = float(value)
    return out


@dataclass(frozen=True)
class FraudParams:
    # Age misrepresentation runs on `features.maturity_mismatch`, which is
    # height_z minus velocity_z against the stated age. A player who is big for
    # the age on their record *and* has stopped growing has a body that finished a
    # spurt the record says has not started. Height alone cannot separate that
    # from a genuinely tall child, because they are the same height; only one of
    # them has stopped growing.
    min_maturity_mismatch: float = 1.8

    # A secondary route in for players whose velocity could not be estimated. Pure
    # height, so a higher bar.
    min_height_z_fallback: float = 1.8

    # Only applied where an age lie is worth telling. Above this age there is no
    # youth competition left to qualify for.
    max_age: float = 19.0
    min_age: float = 11.0

    min_measurements: int = 3


def impossible_rows(pf: PlayerFeatures) -> list[tuple[str, str]]:
    """Every performance row of this player's that breaks arithmetic.

    Returns (entry_id, reason). Row level rather than player level because the
    answer key records the ids of the injected rows, and because a carrier also
    has perfectly ordinary rows: "this player has a self-submitted entry" does not
    identify the bad ones.
    """
    found: list[tuple[str, str]] = []
    for entry in pf.performance:
        if not isinstance(entry, dict):
            continue
        metrics = entry.get("metrics") or {}
        if not isinstance(metrics, dict):
            continue
        for description, required, predicate in IMPOSSIBLE_ROW_RULES:
            values = _numeric(metrics, required)
            if values is not None and predicate(values):
                found.append((entry.get("id", ""), description))
                break
    return found


def detect_impossible_metrics(features: FeatureSet) -> dict[str, str]:
    """Players carrying at least one arithmetically impossible performance row."""
    flagged: dict[str, str] = {}
    for pf in features.players.values():
        rows = impossible_rows(pf)
        if rows:
            reasons = sorted({reason for _, reason in rows})
            flagged[pf.player_id] = (
                f"{len(rows)} self-reported match rows do not add up "
                f"({', '.join(reasons)})."
            )
    return flagged


def detect_age_misrepresentation(
    features: FeatureSet, params: FraudParams | None = None
) -> dict[str, str]:
    """Players whose body is further through maturity than the record allows."""
    params = params or FraudParams()
    flagged: dict[str, str] = {}

    for pf in features.players.values():
        if pf.height_z_mean is None or len(pf.heights) < params.min_measurements:
            continue
        if not (params.min_age <= pf.stated_age <= params.max_age):
            continue

        if pf.maturity_mismatch is not None:
            if pf.maturity_mismatch < params.min_maturity_mismatch:
                continue
            flagged[pf.player_id] = (
                f"Stands {pf.height_z_mean:+.1f} standard deviations from the median "
                f"height for the recorded age of {pf.stated_age:.0f}, while growing "
                f"{pf.velocity_z:+.1f} standard deviations slower than that age group. "
                f"Big for the age on the record and no longer growing, which is the "
                f"pattern of a player who is older than the record says."
            )
        elif pf.height_z_mean >= params.min_height_z_fallback:
            # No usable velocity estimate, so this rests on height alone and is
            # correspondingly weaker. The sentence says so.
            flagged[pf.player_id] = (
                f"Stands {pf.height_z_mean:+.1f} standard deviations above the median "
                f"height for the recorded age of {pf.stated_age:.0f}. There is not "
                f"enough measurement history to check the growth rate, so this rests "
                f"on size alone."
            )

    return flagged


def detect(features: FeatureSet, params: FraudParams | None = None) -> dict[str, str]:
    """Both rules, combined. This is what the headline fraud number is scored on."""
    flagged = dict(detect_age_misrepresentation(features, params))
    for player_id, reason in detect_impossible_metrics(features).items():
        # A player can trip both rules. Keep both sentences: the integrity board
        # should see that the record is inconsistent in two independent ways.
        flagged[player_id] = (
            f"{flagged[player_id]} {reason}" if player_id in flagged else reason
        )
    return flagged


def flagged_entry_ids(features: FeatureSet) -> set[str]:
    """Ids of every performance row that breaks arithmetic.

    Scored against `ground_truth.flagged_performance_entry_ids`, which is the
    row-level answer key rather than the player-level one.
    """
    return {
        entry_id
        for pf in features.players.values()
        for entry_id, _ in impossible_rows(pf)
        if entry_id
    }
