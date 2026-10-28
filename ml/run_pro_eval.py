"""Command-line entry point for the pro tier evaluation: the breakout detector and finishing
against expected goals, scored against the synthetic league's answer key.

    # the reporting seeds (the numbers in ml/README.md, "Pro tier")
    python -m ml.run_pro_eval

    # the tuning run: seeds 101, 202 and 303 only, over the detector's grid
    python -m ml.run_pro_eval --tune

    # other seeds
    python -m ml.run_pro_eval --seed-sweep 7 99

Run from the repository root. The league is built in memory from the seed, so there is no
export to go stale. See ml/pro/evaluate.py for what is measured.
"""

from __future__ import annotations

import argparse
import statistics
import sys

from ml.evaluation.metrics import Score
from ml.pro import breakout
from ml.pro import evaluate as pro_eval

REPORT_SEEDS = [20260827, 7, 99, 404, 555]
TUNING_SEEDS = [101, 202, 303]
THRESHOLDS = [round(0.03 + 0.02 * i, 2) for i in range(16)]
PER90_WEIGHTS = [0.0, 0.1, 0.2, 0.3, 0.5]
MINUTES_ONLY = [0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4]


def _pooled(name: str, scores: list[Score]) -> Score:
    return Score(name, sum(s.tp for s in scores), sum(s.fp for s in scores),
                 sum(s.fn for s in scores), sum(s.tn for s in scores))


def _line(score: Score) -> str:
    lo, hi = score.precision_ci
    rlo, rhi = score.recall_ci
    return (f"{score.detector:42}{score.tp:>5}{score.fp:>5}{score.fn:>5}"
            f"{score.precision:>8.3f} [{lo:.2f}, {hi:.2f}]{score.recall:>8.3f} [{rlo:.2f}, {rhi:.2f}]"
            f"{score.f1:>8.3f}")


def _header() -> str:
    return f"{'':42}{'TP':>5}{'FP':>5}{'FN':>5}{'precision':>22}{'recall':>22}{'F1':>8}"


def tune(seeds: list[int]) -> int:
    data = [pro_eval.league_data(s) for s in seeds]
    grid = []
    for threshold in THRESHOLDS:
        pooled = _pooled("", [pro_eval.score_breakouts(d, threshold) for d in data])
        grid.append((pooled.f1, pooled.precision, pooled.recall, threshold))
    print(f"Breakout v1 (share of the team's chances) on seeds {seeds}, pooled; best 6 by F1")
    print(f"{'F1':>6}{'prec':>7}{'recall':>8}{'threshold':>11}")
    for f1, p, r, t in sorted(grid, reverse=True)[:6]:
        print(f"{f1:>6.3f}{p:>7.3f}{r:>8.3f}{t:>11.2f}")
    grid = []
    for weight in PER90_WEIGHTS:
        for threshold in THRESHOLDS:
            pooled = _pooled("", [pro_eval.score_per90(d, threshold, weight) for d in data])
            grid.append((pooled.f1, pooled.precision, pooled.recall, weight, threshold))
    print()
    print("First version (per 90 rate plus minutes); best 6 by F1")
    print(f"{'F1':>6}{'prec':>7}{'recall':>8}{'min. weight':>13}{'threshold':>11}")
    for f1, p, r, w, t in sorted(grid, reverse=True)[:6]:
        print(f"{f1:>6.3f}{p:>7.3f}{r:>8.3f}{w:>13.1f}{t:>11.2f}")
    best = []
    for threshold in MINUTES_ONLY:
        pooled = _pooled("", [pro_eval.score_minutes_only(d, threshold) for d in data])
        best.append((pooled.f1, threshold))
    f1, threshold = max(best)
    print(f"\nminutes-only baseline: best threshold {threshold} (F1 {f1:.3f})")
    print(f"\nshipped: threshold {breakout.THRESHOLD}")
    return 0


# The minutes-only baseline's threshold, chosen by `--tune` on the tuning seeds.
MINUTES_ONLY_THRESHOLD = 0.25


def report(seeds: list[int]) -> int:
    rows: dict[str, list[Score]] = {"v1": [], "v1, no age window": [], "per 90 rate": [], "minutes only": []}
    finishing = []
    reasons: dict[str, int] = {}
    for seed in seeds:
        print(f"building league for seed {seed} ...", file=sys.stderr)
        data = pro_eval.league_data(seed)
        rows["v1"].append(pro_eval.score_breakouts(data))
        rows["v1, no age window"].append(pro_eval.score_breakouts(data, age_window=False))
        rows["per 90 rate"].append(pro_eval.score_per90(data))
        rows["minutes only"].append(pro_eval.score_minutes_only(data, MINUTES_ONLY_THRESHOLD))
        finishing.append(pro_eval.score_finishing(data))
        for reason, n in pro_eval.unscorable(data).items():
            reasons[reason] = reasons.get(reason, 0) + n

    print(f"Breakouts, seeds {seeds}")
    print(_header())
    for name, scores in rows.items():
        for seed, score in zip(seeds, scores):
            print(_line(Score(f"{name}, seed {seed}", score.tp, score.fp, score.fn, score.tn)))
        print(_line(_pooled(f"{name}, all seeds", scores)))
        print()
    support = sum(s.support for s in rows["v1"])
    print(f"Planted breakouts v1 cannot score, of {support}:")
    for reason, n in reasons.items():
        print(f"  {reason}: {n}")

    print(f"\nFinishing against xG, seeds {seeds} (summed)")
    a = [sum(f.above_single[i] for f in finishing) for i in (0, 1)]
    c = [sum(f.above_career[i] for f in finishing) for i in (0, 1)]
    good = sum(f.good_judgeable for f in finishing), sum(f.good_found for f in finishing)
    ordinary = sum(f.ordinary_seasons for f in finishing), sum(f.ordinary_flagged for f in finishing)
    print(f"  one season 'above':      {a[0]:>4}, truly better finishers {a[1]} ({a[1] / max(1, a[0]):.0%})")
    print(f"  all seasons 'above':     {c[0]:>4}, truly better finishers {c[1]} ({c[1] / max(1, c[0]):.0%})")
    print(f"  truly better finishers judgeable over all seasons: {good[0]}, called 'above': {good[1]}")
    print(f"  ordinary finishers' seasons: {ordinary[0]}, called above or below: {ordinary[1]} "
          f"({ordinary[1] / max(1, ordinary[0]):.0%}; the range is 10th to 90th percentile, so about 20% by chance)")
    pairs = sum(f.pairs for f in finishing)
    print(f"\n  next season's non-penalty goals per 90, {pairs} cases, mean absolute error")
    for name in finishing[0].mae:
        mean = statistics.fmean(f.mae[name] for f in finishing)
        print(f"    predicted by this season's {name:18} {mean:.4f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_pro_eval", description=__doc__.splitlines()[0])
    parser.add_argument("--tune", action="store_true", help="the grid on the tuning seeds")
    parser.add_argument("--seed-sweep", type=int, nargs="+", help="score these seeds instead")
    args = parser.parse_args(argv)
    if args.tune:
        return tune(TUNING_SEEDS)
    return report(args.seed_sweep or REPORT_SEEDS)


if __name__ == "__main__":
    raise SystemExit(main())
