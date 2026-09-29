"""Isolation-forest challenger for age misrepresentation.

The v1 rule (`ml/detectors/fraud.py`) flags a player whose body is further through maturity
than the stated age allows, by a fixed threshold on `maturity_mismatch`. This challenger asks
the same question without a hand-set threshold: which players are unusual, in the space of
growth features, compared with everyone else in the database?

How it decides
--------------
1. The eligible players are the same as the rule's: stated age 11 to 19, at least three height
   readings, and both a height and a growth-rate z score.
2. An isolation forest (Liu et al. 2008) is fitted on four features of those players: mean and
   latest height z for the stated age, growth-rate z, and maturity mismatch (height z minus
   growth-rate z). It scores how few random splits isolate each player; a real anomaly
   separates quickly.
3. `contamination="auto"` uses the paper's own score cut-off. No label, and no count of how
   many frauds exist, is given to it.
4. It flags only anomalies **in the direction age fraud points**: big for the stated age and
   no longer growing (maturity mismatch above zero). An isolation forest also isolates the
   opposite corner, small and still growing fast, which is the late bloomer. Flagging those as
   fraud would accuse exactly the children the platform exists to protect.

Fitted on the whole eligible population each run, like the cohort reference: unsupervised,
using nothing a deployment would not have. Settings fixed before the first run: 300 trees,
`random_state=0`.
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import IsolationForest

from ml.detectors.features import FeatureSet
from ml.detectors.fraud import FraudParams

NAME = "challenger: isolation forest"

_RULE = FraudParams()


def detect_age_misrepresentation(features: FeatureSet) -> dict[str, str]:
    eligible = [
        pf
        for pf in features.players.values()
        if pf.height_z_mean is not None
        and pf.height_z_last is not None
        and pf.velocity_z is not None
        and pf.maturity_mismatch is not None
        and len(pf.heights) >= _RULE.min_measurements
        and _RULE.min_age <= pf.stated_age <= _RULE.max_age
    ]
    if len(eligible) < 20:
        return {}

    x = np.asarray(
        [[pf.height_z_mean, pf.height_z_last, pf.velocity_z, pf.maturity_mismatch] for pf in eligible]
    )
    forest = IsolationForest(n_estimators=300, contamination="auto", random_state=0)
    labels = forest.fit_predict(x)

    flagged: dict[str, str] = {}
    for pf, label in zip(eligible, labels):
        if label == -1 and pf.maturity_mismatch > 0:
            flagged[pf.player_id] = (
                f"Unusual growth for the recorded age of {pf.stated_age:.0f}: "
                f"{pf.height_z_mean:+.1f} standard deviations in height while growing at "
                f"{pf.velocity_z:+.1f} for that age. Big and no longer growing is the pattern of "
                f"an older body."
            )
    return flagged
