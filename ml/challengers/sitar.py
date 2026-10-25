"""Late bloomers by growth timing, with the growth curve fitted too (SITAR proper). It lost too.

    python -m ml.challengers.sitar --seed-sweep 101 202 303            # calibration
    python -m ml.challengers.sitar --seed-sweep 20260827 7 99 404 555   # reported

Why
---
`tempo_fit.py` fitted each child's timing against a fixed reference curve, the dataset's
median height at each age. That median is cross-sectional: children caught at different points
in their spurts, so it is flatter than any one child's curve, and fitting a child against it
underestimated how late they were (planted delays of 1.3 to 2.6 years came out at a median of
0.85). Its write-up named the remedy: fit the curve and the shifts together, as SITAR does
(Cole, Donaldson and Ben-Shlomo 2010).

The method
----------
Per sex, starting from the median curve:

1. Fit every child's time shift `tau` and size factor `A` against the current curve, with the
   priors and the grid search of `tempo_fit.fit` (a small child on time and a big child running
   late draw the same few points, and the priors are what keep the two apart).
2. Re-estimate the curve from everyone's readings with their own shift and size taken out:
   reading (age, cm) of a child becomes (age - tau, cm / A). At each knot the curve is the
   median of the aligned readings within half a year, then made non-decreasing.
3. Centre the shifts and sizes (mean tau 0, mean log A 0), so the curve stays the typical
   child's rather than drifting with the fit.
4. Repeat until the curve settles.

Aligned this way the spurts line up and the curve sharpens, which is what should let a late
child's delay come out at its real size. Flag `tau >= TAU_THRESHOLD` among the children the v1
detector would consider (its own age and reading-count gates).

The caveat that matters most
----------------------------
The generator grows every child as `adult height * fraction(age - maturity offset)`
(data/pipelines/synthetic/growth.py): a size factor and a time shift of one curve, which is
SITAR's own model without the velocity term. So this method is fitting the model the data was
drawn from. Whatever it scores here is a ceiling, not an estimate of how it would do on real
children, whose curves differ in shape as well as timing and size.

Tuning
------
Only `TAU_THRESHOLD`, and whether to combine with v1, are chosen, on seeds 101, 202 and 303.
The priors and grid are `tempo_fit`'s, unchanged, and the curve settings below were set by
reasoning before the first run. Reported seeds are run once, with everything frozen; the frozen
threshold was committed before that run.

Calibration (mean F1; best of eight thresholds, so optimistic): v1 0.557; SITAR alone at best
0.505 (tau >= 0.6); v1 or SITAR tau >= 1.4, 0.585.

Reported seeds, run once (mean F1, pooled TP / FP / FN over five datasets):

    v1 rule                    0.567    36 / 21 / 34
    v1 or SITAR tau >= 1.4     0.549    39 / 33 / 31
    SITAR tau >= 1.4 alone     0.346    19 / 20 / 51

So v1 stays. Three more late bloomers found for twelve more children wrongly flagged.

What it shows: fitting the curve jointly moved the planted late bloomers' fitted delay only from
a median of about 0.85 years (fixed curve) to about 1.05 (0.95 to 1.12 by seed), against true
delays of 1.3 to 2.6. The curve was not the main thing holding the estimate back. Over the 14 to
40 months of readings each child has, the prior on timing, which is what keeps a small child on
time from reading as a big child running late, pulls every estimate toward zero. That is so even
though this method fits the very model the data was drawn from. On real children, with curves
that also differ in shape, it would do no better. More years of readings per child is what
timing needs; a cleverer fit over the same short records is not.

Standard library only, like the v1 detectors.
"""

from __future__ import annotations

import math
import statistics

from ml.challengers import tempo_fit
from ml.detectors.features import FeatureSet, PlayerFeatures
from ml.detectors.late_bloomer import LateBloomerParams

# Set before the first run, by reasoning, not searched.
KNOT_STEP = 0.5          # years between curve knots
KNOT_HALF_WINDOW = 0.5   # aligned readings within this many years of a knot set its height
MIN_POINTS_PER_KNOT = 5  # fewer than this and the knot keeps its previous height
MAX_ITERATIONS = 15
SETTLED_CM = 0.05        # stop when no knot moves more than this
MIN_READINGS_TO_FIT = 2  # a child with one reading cannot show timing

# Chosen on the calibration seeds (101, 202, 303) before the reported seeds were run: the
# best mean F1 there was v1 or a fitted delay of 1.4 years or more (0.585, against 0.557
# for v1 alone; best of eight thresholds from 0.6 to 2.0, so optimistic by construction).
TAU_THRESHOLD = 1.4


def _fit_population(features: FeatureSet, sex: str) -> dict[str, tuple[float, float]]:
    """{player_id: (tau, A)} for every player of this sex with enough readings, against a curve
    fitted jointly with them."""
    curve = [(float(age), cm) for age, cm in tempo_fit.median_curve(features, sex)]
    if not curve:
        return {}
    size_sd = tempo_fit.size_spread(features, sex, [(int(a), cm) for a, cm in curve])
    people = {
        pf.player_id: [(pf.age_at(w), cm) for w, cm in pf.heights]
        for pf in features.players.values()
        if pf.sex == sex and pf.player.get("status") != "merged"
        and len(pf.heights) >= MIN_READINGS_TO_FIT
    }
    low, high = curve[0][0], curve[-1][0]
    knots = [low + k * KNOT_STEP for k in range(int((high - low) / KNOT_STEP) + 1)]
    curve = [(t, tempo_fit._at(curve, t)) for t in knots]

    fitted: dict[str, tuple[float, float]] = {}
    for _ in range(MAX_ITERATIONS):
        fitted = {pid: tempo_fit.fit(readings, curve, size_sd) for pid, readings in people.items()}
        if not fitted:
            return {}
        # Centre: the curve is the typical child's, so mean shift 0 and mean log size 0.
        tau_bar = statistics.fmean(tau for tau, _ in fitted.values())
        log_a_bar = statistics.fmean(math.log(a) for _, a in fitted.values())
        aligned = sorted(
            (age - (tau - tau_bar), cm / math.exp(math.log(a) - log_a_bar))
            for pid, (tau, a) in fitted.items()
            for age, cm in people[pid]
        )
        new_curve = []
        for (t, old), height in zip(curve, _knot_heights(aligned, knots)):
            new_curve.append((t, height if height is not None else old))
        # Height does not go down: running maximum.
        running = 0.0
        new_curve = [(t, (running := max(running, h))) for t, h in new_curve]
        moved = max(abs(h - old) for (_, h), (_, old) in zip(new_curve, curve))
        curve = new_curve
        if moved < SETTLED_CM:
            break
    return {pid: tempo_fit.fit(readings, curve, size_sd) for pid, readings in people.items()}


def _knot_heights(aligned: list[tuple[float, float]], knots: list[float]) -> list[float | None]:
    ages = [a for a, _ in aligned]
    import bisect

    out = []
    for t in knots:
        lo = bisect.bisect_left(ages, t - KNOT_HALF_WINDOW)
        hi = bisect.bisect_right(ages, t + KNOT_HALF_WINDOW)
        window = [cm for _, cm in aligned[lo:hi]]
        out.append(statistics.median(window) if len(window) >= MIN_POINTS_PER_KNOT else None)
    return out


def fitted_taus(features: FeatureSet, params: LateBloomerParams | None = None) -> dict[str, float]:
    """{player_id: tau} for every child the v1 detector would consider."""
    params = params or LateBloomerParams()
    out: dict[str, float] = {}
    for sex in {pf.sex for pf in features.players.values()}:
        fits = _fit_population(features, sex)
        for pid, (tau, _) in fits.items():
            pf: PlayerFeatures = features.players[pid]
            if tempo_fit.eligible(pf, params):
                out[pid] = tau
    return out


def detect(features: FeatureSet, params: LateBloomerParams | None = None) -> dict[str, float]:
    """{player_id: tau} for every considered child whose spurt is TAU_THRESHOLD years late."""
    return {pid: tau for pid, tau in fitted_taus(features, params).items() if tau >= TAU_THRESHOLD}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import tempfile
    from pathlib import Path

    from ml.detectors import late_bloomer
    from ml.evaluation.metrics import score_ids
    from ml.run_backtest import _generate

    parser = argparse.ArgumentParser(prog="sitar", description=__doc__.split("\n")[0])
    parser.add_argument("--seed-sweep", type=int, nargs="+", required=True, metavar="SEED")
    parser.add_argument(
        "--thresholds", type=float, nargs="*", default=None,
        help="Calibration only: also score these timing thresholds.",
    )
    args = parser.parse_args(argv)

    rows = []
    with tempfile.TemporaryDirectory(prefix="northstar-sitar-") as tmp:
        for seed in args.seed_sweep:
            out = Path(tmp) / str(seed)
            _generate(seed, out, attrition=False, players=None)
            features = FeatureSet(out)
            truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
            planted = {c["player_id"] for c in truth["cases"]["late_bloomers"]}
            v1 = set(late_bloomer.detect(features))
            fixed = set(tempo_fit.detect(features))
            taus = fitted_taus(features)
            rows.append((planted, set(features.players), v1, fixed, taus))
            planted_taus = sorted(t for pid, t in taus.items() if pid in planted)
            if planted_taus:
                print(f"seed {seed}: fitted delay of planted late bloomers, median "
                      f"{statistics.median(planted_taus):.2f} years ({len(planted_taus)} considered)")

    def report(name, pick):
        scores = [score_ids(name, pick(v1, fixed, taus), planted, pop)
                  for planted, pop, v1, fixed, taus in rows]
        print(
            f"{name:34s} mean F1 {statistics.fmean(s.f1 for s in scores):.3f}   "
            f"TP {sum(s.tp for s in scores)}  FP {sum(s.fp for s in scores)}  "
            f"FN {sum(s.fn for s in scores)}   per seed " + " ".join(f"{s.f1:.3f}" for s in scores)
        )

    report("v1 rule", lambda v1, fixed, taus: v1)
    report(f"fixed-curve fit, tau >= {tempo_fit.TAU_THRESHOLD}", lambda v1, fixed, taus: fixed)
    thresholds = args.thresholds if args.thresholds else [TAU_THRESHOLD]
    for t in thresholds:
        report(f"SITAR, tau >= {t}", lambda v1, fixed, taus, t=t: {p for p, x in taus.items() if x >= t})
        report(f"v1 or SITAR tau >= {t}",
               lambda v1, fixed, taus, t=t: v1 | {p for p, x in taus.items() if x >= t})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
