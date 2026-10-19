"""Fraud detector, v2 (v1 plus performance evidence for age misrepresentation).

The answer key plants three kinds of fraud under one label, and they are nothing
alike (counts for the default 212-player dataset):

  age_misrepresentation                    9 of the 17 cases
      A recorded date of birth younger than the real one. The body and the season
      were generated from the true age, so the player is too big, too fast and too
      dominant for the age on the record. Hard, statistical, and the one that
      matters: this is the fraud that actually happens in youth football. v1 read
      the body only; v2 also reads output for the stated age, because an early
      maturer's body looks the same (see FraudParams).

  implausible_self_reported_performance    5 of the 17 cases
      Self-submitted match rows whose numbers do not survive arithmetic. More
      goals than shots. More passes completed than attempted. A distance covered
      that no human has run. Easy, deterministic, and worth catching at the point
      of entry rather than by a model at all.

  result_tampering                         3 of the 17 cases
      A table tennis player logs a match they lost as a win, while the opponent's
      own row of the same match still records the loss. Only table tennis has this
      evidence: a match between two registered players is logged by both of them
      (docs/decisions/0004). Deterministic like the arithmetic rule, but it needs
      two records, so it cannot run at entry; who is flagged follows which row is
      verified (`detect_result_contradictions`). A changed result whose opponent
      never logged the match is invisible to it, by design: one match in eight is
      logged by one side only, honestly.

Scoring them as one number hides everything interesting, so this module exposes
each rule separately as well as combined, and the harness reports the
breakdown. A combined F1 of 0.8 that is 5 easy cases and 6 of 9 hard ones is a
different result from 0.8 spread evenly, and only one of them is worth shipping.

The arithmetic rule is not machine learning and should not pretend to be. It is
an integrity check that belongs in ingest validation, and it now is: the rule is
the sport modules' own check (`ml/sport_modules.py`), the same one ingest runs.
The fact that it scores perfectly here is a statement about the generator, not
about a model. It is
included because the answer key labels those players and recall is measured
against all 14.
"""

from __future__ import annotations

from dataclasses import dataclass

from ml import sport_modules

from .features import FeatureSet, PlayerFeatures

# Rows are flagged when their sport module says a present value cannot be true: out of range,
# or breaking a cross-field rule such as "no more goals than shots". The rules live in
# packages/shared/sports/<sport>.json, and ingest validation reads the same ones, so the two
# cannot drift, and a new sport's rules apply here without a change to this file.
#
# Only present values are judged. A missing field means unknown and not zero. Reading absence
# as zero makes "scored without playing" fire on any row that records a goal without
# recording minutes, which is an ordinary shape for a partial import and would have put a
# fraud flag on a real child's record. A test caught it; see
# `test_ordinary_rows_are_not_caught`. That is why this calls `impossibilities`, which ignores
# missing and malformed fields, and not `validate`, which reports them.


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

    # Performance, from `features.output_z`: shots and chances created per minute in football,
    # service winners and unforced errors per set in table tennis, against the role and then
    # against the stated-age cohort. Since every synthetic child got a maturity timing, growth
    # alone flags early maturers, who are big and finished growing for their age exactly as an
    # older boy under a younger birth date is. So an accusation now needs two lines of evidence:
    #
    #   growth-led       the growth rule above, plus output at least a little above the
    #                    stated-age cohort. An early maturer who plays like his age group is
    #                    no longer accused.
    #   performance-led  output well above the stated-age cohort, plus a body clearly big for
    #                    the stated age. This reaches the 11 to 13 band, where a boy two years
    #                    older has not yet started the spurt that would give him away.
    #
    # A player with no output to read (too few minutes or sets) is judged on growth alone, as
    # before. Tuned on seeds 101, 202 and 303 only; see ml/README.md for the grid and for the
    # what-if in which early maturers also outplay their age group.
    min_output_z_with_growth: float = 0.5
    min_output_z: float = 1.25
    min_height_z_with_output: float = 1.0


def impossible_rows(pf: PlayerFeatures) -> list[tuple[str, str]]:
    """Every performance row of this player's that its sport module says cannot be true.

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
        problems = sport_modules.impossibilities(metrics, entry.get("schema_ref", ""))
        if problems:
            found.append((entry.get("id", ""), problems[0]))
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
    """Players whose body and output are further along than the record allows."""
    params = params or FraudParams()
    flagged: dict[str, str] = {}

    for pf in features.players.values():
        if pf.height_z_mean is None or len(pf.heights) < params.min_measurements:
            continue
        if not (params.min_age <= pf.stated_age <= params.max_age):
            continue

        reason = _growth_reason(pf, params)
        output_z = pf.output_z
        if output_z is None:
            # Nothing to read about output, so growth decides alone, as the rule did before
            # performance was added. The sentence says so.
            if reason:
                flagged[pf.player_id] = (
                    f"{reason} There is not enough playing time on record to check this "
                    f"against performance."
                )
            continue

        output = (
            f"outproduces players recorded as {pf.stated_age:.0f} by {output_z:+.1f} "
            f"standard deviations for the time played"
        )
        if reason and output_z >= params.min_output_z_with_growth:
            flagged[pf.player_id] = f"{reason} The player also {output}."
        elif (
            output_z >= params.min_output_z
            and pf.height_z_mean >= params.min_height_z_with_output
        ):
            flagged[pf.player_id] = (
                f"Dominates the age group on the record: {output}, and stands "
                f"{pf.height_z_mean:+.1f} standard deviations above the median height for "
                f"that age. Output and size together are the pattern of a player who is "
                f"older than the record says."
            )

    return flagged


def _growth_reason(pf: PlayerFeatures, params: FraudParams) -> str | None:
    """The v1 growth rule, as a sentence when it fires and None when it does not."""
    if pf.maturity_mismatch is not None:
        if pf.maturity_mismatch < params.min_maturity_mismatch:
            return None
        return (
            f"Stands {pf.height_z_mean:+.1f} standard deviations from the median "
            f"height for the recorded age of {pf.stated_age:.0f}, while growing "
            f"{pf.velocity_z:+.1f} standard deviations slower than that age group. "
            f"Big for the age on the record and no longer growing, which is the "
            f"pattern of a player who is older than the record says."
        )
    if pf.height_z_mean >= params.min_height_z_fallback:
        # No usable velocity estimate, so this rests on height alone and is
        # correspondingly weaker. The sentence says so.
        return (
            f"Stands {pf.height_z_mean:+.1f} standard deviations above the median "
            f"height for the recorded age of {pf.stated_age:.0f}. There is not "
            f"enough measurement history to check the growth rate, so this rests "
            f"on size alone."
        )
    return None


def detect(features: FeatureSet, params: FraudParams | None = None) -> dict[str, str]:
    """Every rule, combined. This is what the headline fraud number is scored on."""
    flagged = dict(detect_age_misrepresentation(features, params))
    for rule in (detect_impossible_metrics, detect_result_contradictions):
        for player_id, reason in rule(features).items():
            # A player can trip more than one rule. Keep every sentence: the integrity
            # board should see each independent way the record is inconsistent.
            flagged[player_id] = (
                f"{flagged[player_id]} {reason}" if player_id in flagged else reason
            )
    return flagged


# A match between two registered players is logged as two rows that point at each other: the
# same date, each naming the other in `opponent_player_id`. What one side won the other lost.
# These are the fields that must mirror, as (this side, the other side).
MIRRORED_FIELDS = (("sets_won", "sets_lost"), ("points_won", "points_lost"))


def _mirrors(a: dict, b: dict) -> bool | None:
    """True if two rows of one match agree, False if they contradict, None if unknown.

    Unknown when any compared value is missing or not a number: absence is not zero (see the
    note at the top of this module), and an incomplete row cannot contradict anything.
    """
    ma, mb = a.get("metrics") or {}, b.get("metrics") or {}
    for mine, theirs in MIRRORED_FIELDS:
        values = (ma.get(mine), ma.get(theirs), mb.get(mine), mb.get(theirs))
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            return None
    return all(ma[x] == mb[y] and ma[y] == mb[x] for x, y in MIRRORED_FIELDS)


def contradicting_matches(features: FeatureSet) -> list[tuple[dict, dict]]:
    """Pairs of rows, (one side, the other side), of the same match that disagree.

    Two players can meet more than once on a day, so the rows of a day are paired off first:
    each row of one side with a row of the other side that mirrors it. What is left over on
    both sides is a contradiction, paired in date order. A row left over on one side only is a
    match the other player never logged, which is common and honest, so it is not evidence;
    likewise an extra row that agrees with an already-paired one is a duplicate entry, not a
    changed result. Rows of merged records are left out; they are copies.
    """
    merged = {pid for pid, pf in features.players.items() if pf.player.get("status") == "merged"}
    sides: dict[tuple[str, str, str], list[dict]] = {}
    for e in features.raw["performance_entries"]:
        opponent = e.get("opponent_player_id")
        if not opponent or e.get("player_id") in merged or opponent in merged:
            continue
        key = (str(e["player_id"]), str(opponent), str(e.get("period_start"))[:10])
        sides.setdefault(key, []).append(e)

    found = []
    for (player, opponent, played_on), rows in sides.items():
        if player > opponent:
            continue  # each day once, from the side whose id sorts first
        others = list(sides.get((opponent, player, played_on), []))
        left = []
        for row in rows:
            partner = next((o for o in others if _mirrors(row, o) is True), None)
            if partner is not None:
                others.remove(partner)
            else:
                left.append(row)
        # A row that is unknown against every candidate (a missing value) proves nothing.
        left = [r for r in left if any(_mirrors(r, o) is False for o in others)]
        others = [o for o in others if any(_mirrors(r, o) is False for r in left)]
        found.extend(zip(left, others))
    return found


def detect_result_contradictions(features: FeatureSet) -> dict[str, str]:
    """Players whose own row of a match contradicts the opponent's row of it.

    Who is flagged follows how far each row can be trusted. Against a verified row (coach
    logged or from an official source), the unverified side is flagged. If neither row is
    verified, both are, as one conflict for a reviewer, because nothing says which one is
    true. If both are verified, it is a data error between two trusted sources, not fraud, and
    nothing is flagged.
    """
    flagged: dict[str, list[str]] = {}
    for a, b in contradicting_matches(features):
        played_on = str(a.get("period_start"))[:10]
        a_ok, b_ok = a.get("is_validated") is True, b.get("is_validated") is True
        if a_ok and b_ok:
            continue
        if a_ok != b_ok:
            liar, truth = (b, a) if a_ok else (a, b)
            m = liar["metrics"]
            flagged.setdefault(str(liar["player_id"]), []).append(
                f"Their own row of the match on {played_on} records {m['sets_won']}-"
                f"{m['sets_lost']} in sets; the opponent's verified row of the same match "
                f"records {truth['metrics']['sets_won']}-{truth['metrics']['sets_lost']} "
                f"the other way."
            )
            continue
        for row in (a, b):
            flagged.setdefault(str(row["player_id"]), []).append(
                f"Two self-submitted rows of the match on {played_on} disagree about the "
                f"result, and neither is verified. Flagged on both sides for a reviewer; this "
                f"does not say which one is true."
            )
    return {pid: " ".join(reasons) for pid, reasons in flagged.items()}


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
