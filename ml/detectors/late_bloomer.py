"""Late-bloomer detector, v1.

What the phenomenon is
----------------------
A late bloomer is short for their age group during early adolescence and then
catches up, sometimes overtaking. The scouting failure this project exists to fix
is that they get released at 14 for being small, when what they actually are is
young for their body, not small for their eventual one.

What separates them from a player who is simply short
-----------------------------------------------------
Height alone cannot tell the two apart, and a detector built on height alone will
flag every short child in the academy. The discriminator is the pair of signals
together:

  1. below the cohort median for their stated age, and
  2. still growing fast at an age where most of their peers have slowed.

A genuinely short player tracks below the median and grows at a normal rate for
their age. A late bloomer tracks below the median *and* carries a growth velocity
that belongs to a younger child, because developmentally that is what they are.

This is a rule, not a model
---------------------------
v1 is deliberately a threshold rule over two features. It is a floor to beat, it
is auditable by a coach, and every flag it produces can be explained in one
sentence, which the application track needs anyway (see the player profile screen:
"every flag carries the sentence that explains why it fired"). The maturity-offset
spike on the board is what replaces it with an estimate rather than a rule.

`features.maturity_mismatch`, which the fraud detector leans on, was tried here
as a third gate and removed again. It changed nothing: every player the height and
velocity rules already agreed on, it also agreed on. Recording that here so the
next person does not spend an afternoon rediscovering it.

Thresholds were chosen on datasets generated from seeds 101, 202 and 303, and are
reported on the committed default seed. See `ml/README.md` for why that split
matters.
"""

from __future__ import annotations

from dataclasses import dataclass

from .features import FeatureSet, PlayerFeatures


@dataclass(frozen=True)
class LateBloomerParams:
    # Only adolescents are eligible. A 24-year-old cannot be a late bloomer,
    # because the question is when the spurt arrived and theirs already did. The
    # generator plants them in 11.5 to 17.0, and they age forward from there.
    min_age: float = 11.0
    max_age: float = 18.5

    # How far below the cohort median counts as short. Averaged across the whole
    # series rather than taken at the last measurement, because a single reading
    # is noisy and a player mid-catch-up may already be back near the median.
    max_height_z_mean: float = -0.9

    # Centimetres per year over the most recent window. The catch-up signal in raw
    # units, which keeps a player with no cohort velocity reference eligible.
    min_recent_velocity: float = 3.0

    # A player needs enough history for the velocity to be meaningful.
    min_measurements: int = 3


def explain(pf: PlayerFeatures) -> str:
    """The sentence that goes on the flag. See the player profile wireframe."""
    return (
        f"Tracking {abs(pf.height_z_mean or 0):.1f} standard deviations below the median "
        f"height for age {pf.stated_age:.0f}, but still growing at "
        f"{pf.recent_velocity:.1f} cm/year. Short for his age group and still climbing, "
        f"which is the late-maturing pattern rather than a low ceiling."
    )


def detect(
    features: FeatureSet, params: LateBloomerParams | None = None
) -> dict[str, str]:
    """Return {player_id: reason} for every player flagged as a late bloomer."""
    params = params or LateBloomerParams()
    flagged: dict[str, str] = {}

    for pf in features.players.values():
        if pf.height_z_mean is None or len(pf.heights) < params.min_measurements:
            continue
        if not (params.min_age <= pf.stated_age <= params.max_age):
            continue
        if pf.height_z_mean > params.max_height_z_mean:
            continue
        if pf.recent_velocity < params.min_recent_velocity:
            continue
        flagged[pf.player_id] = explain(pf)

    return flagged
