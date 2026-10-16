"""Late bloomers by growth timing: a SITAR-style fit, measured against the v1 rule. It lost.

    python -m ml.challengers.tempo_fit --seed-sweep 101 202 303           # calibration
    python -m ml.challengers.tempo_fit --seed-sweep 20260827 7 99 404 555  # reported

Why it was tried
----------------
An error analysis of v1 on the calibration seeds (101, 202, 303) found that 17 of its 18 missed
late bloomers failed the height gate, not the growth gate: they were not short. What sets a
late bloomer apart is timing, a spurt that arrives late, and growth research estimates timing
by fitting each child to the population curve shifted in time and scaled in size (the SITAR
model: size, tempo, velocity; Cole, Donaldson and Ben-Shlomo 2010).

The method
----------
For each player with at least `min_measurements` height readings, aged `min_age` to `max_age`
by stated age (the v1 detector's own gates), find the time shift `tau` and size factor `A` that
best fit the readings to `A * g(age - tau)`, where `g` is the median height curve of their sex
in the same dataset, linear between whole years. Stated age throughout, for the reason
`features.height_z` gives. Flag `tau >= TAU_THRESHOLD`: the spurt is that many years late.

Fitted by least squares over a grid of `tau`, with `A` solved in closed form, and two priors,
because `tau` and `A` trade off over a short series (a small child on time and a big child
running late can draw the same few points). Without the priors the two estimates correlated at
0.7 on the calibration seeds and the timing estimates of ordinary children spread 1.7 years.

- `A` around 1, with the spread of adult height in the same dataset (grown players, 20+).
- `tau` around 0, spread `TAU_PRIOR_YEARS`, a round figure for how much children's timing
  varies. Deliberately not the generator's own setting, so the fit is not told how the data
  was made.

How it was tuned, all on seeds 101, 202 and 303
-------------------------------------------------
1. Plain least squares: best mean F1 0.345 (threshold 0.4), against 0.557 for v1.
2. With the priors (`RESIDUAL_CM` 1.0, `TAU_PRIOR_YEARS` 1.0, set by reasoning, not searched):
   best 0.488, at `TAU_THRESHOLD` 0.8.
3. Flagging v1 *or* a late fit, to add the tall late bloomers v1 cannot see: best 0.538, at a
   timing threshold of 1.8. Never above v1 alone at any threshold tried (0.8 to 1.8).

Reported seeds, settings frozen, run once (mean F1, pooled TP / FP / FN over five datasets):

    v1 rule                    0.567    36 / 21 / 34
    timing fit, tau >= 0.8     0.477    44 / 69 / 26
    v1 or tau >= 1.8           0.554    39 / 31 / 31

The fit finds more late bloomers than v1 and accuses three times as many other children, so v1
stays. The likeliest reason: the median curve is cross-sectional, an average of children at
different points in their spurts, which makes it flatter than any one child's. Fitting a child
against it underestimates how late they are (planted delays are 1.3 to 2.6 years; the median
fitted delay for them was 0.85). Real SITAR fits the curve and the shifts together; that, and
more years of history per child, is what this would need to compete.

Standard library only, like the v1 detectors.
"""

from __future__ import annotations

import bisect
import statistics

from ml.detectors.features import FeatureSet, PlayerFeatures
from ml.detectors.late_bloomer import LateBloomerParams

# All fixed before the reported seeds were run. See the module docstring for how.
RESIDUAL_CM = 1.0
TAU_PRIOR_YEARS = 1.0
TAU_THRESHOLD = 0.8
TAU_GRID = [k * 0.05 for k in range(-60, 61)]
# Used only when a dataset has fewer than five grown players of a sex.
FALLBACK_SIZE_SPREAD = 0.05
ADULT_AGE = 20.0


def median_curve(features: FeatureSet, sex: str) -> list[tuple[int, float]]:
    """(age, median height) for one sex, from the detectors' own height reference."""
    return sorted((age, median) for (s, age), (median, _) in features.height_reference.items() if s == sex)


def _at(curve: list[tuple[int, float]], age: float) -> float:
    ages = [a for a, _ in curve]
    if age <= ages[0]:
        return curve[0][1]
    if age >= ages[-1]:
        return curve[-1][1]
    i = bisect.bisect_right(ages, age)
    (a0, h0), (a1, h1) = curve[i - 1], curve[i]
    return h0 + (age - a0) / (a1 - a0) * (h1 - h0)


def size_spread(features: FeatureSet, sex: str, curve: list[tuple[int, float]]) -> float:
    """How much grown players of this sex vary in height, as a fraction of the median."""
    ratios = [
        pf.heights[-1][1] / _at(curve, pf.age_at(pf.heights[-1][0]))
        for pf in features.players.values()
        if pf.sex == sex and pf.heights and pf.age_at(pf.heights[-1][0]) >= ADULT_AGE
    ]
    return statistics.pstdev(ratios) if len(ratios) >= 5 else FALLBACK_SIZE_SPREAD


def fit(
    readings: list[tuple[float, float]], curve: list[tuple[int, float]], size_sd: float
) -> tuple[float, float]:
    """(tau, A) for readings given as (stated age, cm). Positive tau is a late spurt."""
    best: tuple[float, float, float] | None = None
    for tau in TAU_GRID:
        g = [_at(curve, age - tau) for age, _ in readings]
        # A in closed form, with its prior around 1.
        num = sum(h * gi for (_, h), gi in zip(readings, g)) / RESIDUAL_CM**2 + 1 / size_sd**2
        den = sum(gi * gi for gi in g) / RESIDUAL_CM**2 + 1 / size_sd**2
        size = num / den
        objective = (
            sum((h - size * gi) ** 2 for (_, h), gi in zip(readings, g)) / RESIDUAL_CM**2
            + (tau / TAU_PRIOR_YEARS) ** 2
            + ((size - 1) / size_sd) ** 2
        )
        if best is None or objective < best[0] - 1e-12:
            best = (objective, tau, size)
    return best[1], best[2]


def eligible(pf: PlayerFeatures, params: LateBloomerParams) -> bool:
    return (
        pf.player.get("status") != "merged"
        and len(pf.heights) >= params.min_measurements
        and params.min_age <= pf.stated_age <= params.max_age
    )


def detect(features: FeatureSet, params: LateBloomerParams | None = None) -> dict[str, float]:
    """{player_id: fitted tau} for every player whose fitted spurt is TAU_THRESHOLD years late."""
    params = params or LateBloomerParams()
    curves = {sex: median_curve(features, sex) for sex in {pf.sex for pf in features.players.values()}}
    spreads = {sex: size_spread(features, sex, curve) for sex, curve in curves.items() if curve}
    flagged: dict[str, float] = {}
    for pf in features.players.values():
        if not eligible(pf, params) or not curves.get(pf.sex):
            continue
        tau, _ = fit([(pf.age_at(w), cm) for w, cm in pf.heights], curves[pf.sex], spreads[pf.sex])
        if tau >= TAU_THRESHOLD:
            flagged[pf.player_id] = tau
    return flagged


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import tempfile
    from pathlib import Path

    from ml.detectors import late_bloomer
    from ml.evaluation.metrics import score_ids
    from ml.run_backtest import _generate

    parser = argparse.ArgumentParser(prog="tempo_fit", description=__doc__.split("\n")[0])
    parser.add_argument("--seed-sweep", type=int, nargs="+", required=True, metavar="SEED")
    args = parser.parse_args(argv)

    rows = []
    with tempfile.TemporaryDirectory(prefix="northstar-tempo-") as tmp:
        for seed in args.seed_sweep:
            out = Path(tmp) / str(seed)
            _generate(seed, out, attrition=False, players=None)
            features = FeatureSet(out)
            truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
            planted = {c["player_id"] for c in truth["cases"]["late_bloomers"]}
            v1 = set(late_bloomer.detect(features))
            fitted = set(detect(features))
            rows.append((planted, set(features.players), v1, fitted))

    for name, pick in (
        ("v1 rule", lambda v1, fitted: v1),
        (f"timing fit, tau >= {TAU_THRESHOLD}", lambda v1, fitted: fitted),
    ):
        scores = [score_ids(name, pick(v1, fitted), planted, pop) for planted, pop, v1, fitted in rows]
        print(
            f"{name:28s} mean F1 {statistics.fmean(s.f1 for s in scores):.3f}   "
            f"TP {sum(s.tp for s in scores)}  FP {sum(s.fp for s in scores)}  "
            f"FN {sum(s.fn for s in scores)}   per seed "
            + " ".join(f"{s.f1:.3f}" for s in scores)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
