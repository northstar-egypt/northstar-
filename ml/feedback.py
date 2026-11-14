"""Reviewers' decisions back into the detectors: does a confirmed or dismissed flag teach them?

Every flag on the integrity board ends in a decision with a reason (`flag_event`). Each one is
a labelled example: this player, these features, and whether the flag was right. This module
asks whether those examples make the next round of flags better, for the two detectors with
the most room to improve: late bloomer and age misrepresentation.

The loop, as a deployment would run it
--------------------------------------
1. A detector raises **candidates**: the players its rule lets through.
2. Reviewers decide each one. Only candidates are ever decided, so their decisions can teach
   the system which flags were wrong, but say nothing about the players it never raised.
3. A small model is fitted on the decided candidates: their features, and the decision.
4. Next round, the rule raises candidates again and the model keeps only those it thinks a
   reviewer would confirm.

Two ways to use it, measured separately:

- **Filter.** Candidates are the v1 rule's own flags. The model can only drop flags, so it can
  raise precision and can only lose recall.
- **Wider net.** The rule's gates are loosened (`NET_LEVELS`), so reviewers see more players,
  including some the v1 rule misses; the model then picks among them. This is the only way
  decisions can recover a missed child, at the price of more cases to review.

The model is plain logistic regression over the features the rules already read (`FEATURES`),
standardised, with settings fixed before the first run: `C=1`, no class weights, and a flag is
kept when the model gives it at least an even chance of being confirmed (0.5). It is chosen
because it is small enough to fit on a few dozen decisions and its weights can be read.

How it is measured
------------------
`ml/run_feedback_eval.py`. Reviewers are simulated from the planted answer key: a reviewer
who decides every case right, and one who gets one decision in ten wrong. Decisions are made
on the calibration seeds (101, 202, 303) only; the model is then applied to the reported seeds,
as decisions made last season would be applied to this season's records. Which net level to
use is chosen on the calibration seeds alone, by leaving one of them out in turn.

Note what the v1 rules already had: their thresholds were tuned on the calibration seeds with
the **complete** answer key, every player labelled, which is more than reviewers ever see. So
the question is not "labels against no labels" but whether a fitted combination of the same
features, taught only by decisions on raised cases, beats hand-set thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from ml.detectors import fraud, late_bloomer
from ml.detectors.features import FeatureSet, PlayerFeatures
from ml.detectors.fraud import FraudParams
from ml.detectors.late_bloomer import LateBloomerParams

DETECTORS = ("late_bloomer", "age_fraud")

# What the model reads. All are already computed for the rules (detectors/features.py); a
# missing value is filled with 0 and marked by its own 0/1 column, so "no output on record"
# is something the model can learn from rather than a hole.
FEATURES = (
    "stated_age", "height_z_mean", "height_z_last", "height_z_min", "recent_velocity",
    "velocity_z", "maturity_mismatch", "output_z", "readings", "female",
)
_MAY_BE_MISSING = ("height_z_last", "height_z_min", "velocity_z", "maturity_mismatch", "output_z")

# Level 0 is the v1 rule. Each level after it loosens every gate of the rule by one step, so
# reviewers see more players. Fixed before the first run; which level to use is chosen on the
# calibration seeds (`choose_level`).
NET_LEVELS: dict[str, list] = {
    "late_bloomer": [
        LateBloomerParams(),
        replace(LateBloomerParams(), max_height_z_mean=-0.6, min_recent_velocity=2.5),
        replace(LateBloomerParams(), max_height_z_mean=-0.3, min_recent_velocity=2.0),
        replace(LateBloomerParams(), max_height_z_mean=0.0, min_recent_velocity=1.5),
    ],
    "age_fraud": [
        FraudParams(),
        replace(FraudParams(), min_maturity_mismatch=1.4, min_height_z_fallback=1.4,
                min_output_z_with_growth=0.25, min_output_z=1.0, min_height_z_with_output=0.75),
        replace(FraudParams(), min_maturity_mismatch=1.0, min_height_z_fallback=1.0,
                min_output_z_with_growth=0.0, min_output_z=0.75, min_height_z_with_output=0.5),
        replace(FraudParams(), min_maturity_mismatch=0.6, min_height_z_fallback=0.6,
                min_output_z_with_growth=-0.25, min_output_z=0.5, min_height_z_with_output=0.25),
    ],
}

KEEP_AT = 0.5


def candidates(features: FeatureSet, detector: str, level: int = 0) -> set[str]:
    """The players the rule raises at this net level."""
    params = NET_LEVELS[detector][level]
    if detector == "late_bloomer":
        return set(late_bloomer.detect(features, params))
    return set(fraud.detect_age_misrepresentation(features, params))


def vector(pf: PlayerFeatures) -> list[float]:
    values = {
        "stated_age": pf.stated_age,
        "height_z_mean": pf.height_z_mean,
        "height_z_last": pf.height_z_last,
        "height_z_min": pf.height_z_min,
        "recent_velocity": pf.recent_velocity,
        "velocity_z": pf.velocity_z,
        "maturity_mismatch": pf.maturity_mismatch,
        "output_z": pf.output_z,
        "readings": float(len(pf.heights)),
        "female": 1.0 if pf.sex == "female" else 0.0,
    }
    row = [float(values[name]) if values[name] is not None else 0.0 for name in FEATURES]
    row += [1.0 if values[name] is None else 0.0 for name in _MAY_BE_MISSING]
    return row


@dataclass
class Decisions:
    """Decided candidates: one feature row and one verdict (True = confirmed) each."""

    rows: list[list[float]]
    confirmed: list[bool]

    def __len__(self) -> int:
        return len(self.confirmed)

    def __add__(self, other: Decisions) -> Decisions:
        return Decisions(self.rows + other.rows, self.confirmed + other.confirmed)


def decide(
    features: FeatureSet, ids: set[str], truth: set[str], *, wrong: float = 0.0,
    rng: np.random.Generator | None = None,
) -> Decisions:
    """A simulated reviewer's decisions on `ids`: right per the answer key, except that a
    share `wrong` of them, picked at random, go the other way."""
    rng = rng or np.random.default_rng(0)
    rows, confirmed = [], []
    for player_id in sorted(ids):
        verdict = player_id in truth
        if wrong and rng.random() < wrong:
            verdict = not verdict
        rows.append(vector(features.players[player_id]))
        confirmed.append(verdict)
    return Decisions(rows, confirmed)


class Learner:
    """Logistic regression on decided candidates. None of its settings were tuned."""

    def __init__(self, decisions: Decisions):
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        self.n = len(decisions)
        self.constant: bool | None = None
        if len(set(decisions.confirmed)) < 2:
            # Every decision went the same way: nothing to separate. Keep everything when all
            # were confirmed and nothing when all were dismissed, which is what a reviewer's
            # record says.
            self.constant = bool(decisions.confirmed[0]) if decisions.confirmed else True
            self.model = None
            return
        self.model = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000))
        self.model.fit(np.array(decisions.rows), np.array(decisions.confirmed))

    def keep(self, features: FeatureSet, ids: set[str]) -> set[str]:
        """The candidates a reviewer would more likely confirm than dismiss."""
        if not ids:
            return set()
        if self.model is None:
            return set(ids) if self.constant else set()
        ordered = sorted(ids)
        rows = np.array([vector(features.players[i]) for i in ordered])
        chance = self.model.predict_proba(rows)[:, 1]
        return {i for i, p in zip(ordered, chance) if p >= KEEP_AT}
