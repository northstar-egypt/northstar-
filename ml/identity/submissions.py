"""One new record against a register: the checks a diaspora submission gets on arrival
(decision 0011). The API runs these on the database (apps/api/app/services/submissions.py);
ml/submission_eval.py grades them on planted submissions. One piece of code for both, so the
numbers in ml/README.md are about what the app does.

Two checks, both built on the identity engine (`engine`, decision 0010):

- **Likely the same person**: a record scoring at least the engine's link threshold, or one
  with the same full name and given name born within a week of the submission (a typing
  slip, which the engine itself scores low).
- **Same name, different date of birth**: the same full name and given name with a date of
  birth more than a week apart and at most FRAUD_YEARS years. The engine reads a different
  date as strong evidence of two people, so it never links these; but a re-registration with a
  younger date is exactly what age fraud looks like. The engine does not even compare records
  born more than a year apart (its blocking), which on the calibration seeds missed two thirds
  of the planted frauds of 13 to 24 months, so this check looks up to FRAUD_YEARS apart. A
  record raised here may also be a different person of the same name, which only the reviewer
  can tell (ml/README.md, "Diaspora submission checks", measures how often).

How a submission is scored differs from `engine.score` in two ways, both for one record
against many:

- **Only the submission's pairs.** The engine's own blocking (`engine.candidates`: enough shared
  name keys, none in more than MAX_POSTING records, nothing ruling the pair out), but only for
  pairs that include the submission, and the model fitted once on the register (`fit`).
- **The share of true pairs is floored.** Fitted on a register with no duplicates, the
  engine's estimate of how many records repeat each other falls to nothing (1e-12), and then
  no submission could ever match. That estimate answers a different question, so below the
  engine's own starting value (a tenth of the records duplicated) the starting value is used.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

from ml.identity import engine

# How far apart two dates of birth may be for "same name, different date of birth": a judgment,
# wide enough for a player passed off as a year group or two younger, not fitted on any seed.
# The engine's own blocking stops at one calendar year.
FRAUD_YEARS = 3


@dataclass(frozen=True)
class Fitted:
    model: engine.Model
    shares: dict[str, float]
    u_avg: float
    records: int


def fit(register: list[engine.Record]) -> Fitted:
    """The engine fitted on the register, as `engine.score` fits it, with the floor above."""
    _, model = engine.score(register)
    n = len(register)
    everything = max(1, n * (n - 1) // 2)
    model = replace(model, prior=max(model.prior, min(0.5, 0.1 * n / everything)))
    shares = engine.term_shares(register)
    return Fitted(model, shares, sum(x * x for x in shares.values()), n)


def score_one(mine: engine.Record, records: dict[str, engine.Record], fitted: Fitted) -> list[engine.ScoredPair]:
    """`mine` against every record, with the engine's blocking and scoring (see above)."""
    their_keys = {k: engine.keys(r) for k, r in records.items()}
    posting = Counter(key for ks in their_keys.values() for key in ks)
    mine_keys = {k for k in engine.keys(mine) if posting[k] + 1 <= engine.MAX_POSTING}
    out = []
    for k, r in records.items():
        need = max(1, min(2, len(mine_keys), len(their_keys[k])))
        if len(mine_keys & their_keys[k]) < need:
            continue
        blocked = not engine._compatible(mine, r)
        if blocked and not _fraud_window(mine, r):
            continue
        vector = engine.compare(mine, r)
        # Outside the engine's blocking, only for the same-name check.
        if blocked and not (vector.get("name") == "all" and vector.get("given") == "same"):
            continue
        offset = engine.tf_offset(mine, r, vector["name"], fitted.shares, fitted.u_avg)
        out.append(engine.ScoredPair(mine.id, r.id, fitted.model.probability(vector, offset), vector))
    return out


def _fraud_window(a: engine.Record, b: engine.Record) -> bool:
    """Ruled out by the engine only for being born more than a year apart, and within FRAUD_YEARS."""
    if a.sex and b.sex and a.sex != b.sex:
        return False
    if not (a.date_of_birth and b.date_of_birth):
        return False
    return abs((a.date_of_birth - b.date_of_birth).days) <= FRAUD_YEARS * 365.25


def same_name(pair: engine.ScoredPair) -> bool:
    return pair.levels.get("name") == "all" and pair.levels.get("given") == "same"


def classify(scored: list[engine.ScoredPair]) -> tuple[list[engine.ScoredPair], list[engine.ScoredPair]]:
    """(likely the same person, strongest first; same name with a different date of birth)."""
    likely, twins = [], []
    for pair in scored:
        if pair.probability >= engine.LINK or (same_name(pair) and pair.levels.get("dob") == "near"):
            likely.append(pair)
        elif same_name(pair) and pair.levels.get("dob") == "conflict":
            twins.append(pair)
    likely.sort(key=lambda p: -p.probability)
    return likely, twins
