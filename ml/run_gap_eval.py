"""Command-line entry point for the team gap analysis reliability check.

    # the reporting seeds (the numbers in ml/README.md, "Team gap analysis")
    python -m ml.run_gap_eval

    # the tuning run: seeds 101, 202 and 303 only; chooses the minimum minutes
    python -m ml.run_gap_eval --tune

Run from the repository root. Each league is built in memory from its seed. See
ml/pro/gap_eval.py for what is measured.
"""

from __future__ import annotations

import argparse
import statistics
import sys

from ml.pro import gap_eval, gaps
from ml.sport_modules import registry

REPORT_SEEDS = [20260827, 7, 99, 404, 555]
TUNING_SEEDS = [101, 202, 303]


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def _f(value: float | None) -> str:
    return "  n/a" if value is None else f"{value:5.2f}"


def run(seeds: list[int], tune: bool) -> int:
    config = registry()["football"].team_gaps
    data = []
    for seed in seeds:
        print(f"building halves for seed {seed} ...", file=sys.stderr)
        data.append(gap_eval.halves(seed))

    print(f"Team statistics, first half against second half, seeds {seeds} (mean over seeds)")
    print(f"{'':52}{'r':>6}{'bottom third kept':>20}")
    team = [gap_eval.team_reliability(config, d) for d in data]
    for i, metric in enumerate(config.metrics):
        r = _mean(t[i].r for t in team)
        kept = _mean(t[i].bottom_third_kept for t in team)
        print(f"{metric.label:52}{_f(r):>6}{kept:>19.0%}")
    print("(chance alone keeps a third of the bottom third)")

    print("\nPlayer statistics, within position group: half-season r -> season reliability 2r/(1+r)")
    by_threshold: dict[int, dict[str, float | None]] = {}
    header = "".join(f"{t:>11}" for t in gap_eval.THRESHOLDS)
    print(f"{'minutes in the season (half in each half)':42}{header}")
    rows: dict[str, list[str]] = {key: [] for key in config.attributes}
    counts = []
    for threshold in gap_eval.THRESHOLDS:
        per_seed = [gap_eval.player_reliability(config, d, threshold) for d in data]
        by_threshold[threshold] = {key: _mean(p[key][0] for p in per_seed) for key in config.attributes}
        counts.append(round(statistics.fmean(sum(n for _, n in p.values()) / len(p) for p in per_seed)))
        for key in config.attributes:
            r = by_threshold[threshold][key]
            rows[key].append(f"{'':>5}{_f(gap_eval.spearman_brown(r) if r is not None else None)}  ")
    for key, cells in rows.items():
        print(f"{config.attributes[key].label:42}" + "".join(f"{c:>11}" for c in cells))
    medians = []
    for threshold in gap_eval.THRESHOLDS:
        values = [gap_eval.spearman_brown(r) for r in by_threshold[threshold].values() if r is not None]
        medians.append(statistics.median(values) if values else None)
    print(f"{'median':42}" + "".join(f"{'':>5}{_f(m)}  " for m in medians))
    print(f"{'players per statistic (mean)':42}" + "".join(f"{c:>11}" for c in counts))

    chosen = gap_eval.choose_min_minutes(by_threshold)
    print(f"\nsmallest threshold with median season reliability >= {gap_eval.TARGET}: {chosen}")
    if tune:
        print(f"shipped: gaps.MIN_MINUTES = {gaps.MIN_MINUTES}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_gap_eval", description=__doc__.splitlines()[0])
    parser.add_argument("--tune", action="store_true", help="the tuning seeds, which choose the minimum minutes")
    parser.add_argument("--seed-sweep", type=int, nargs="+", help="score these seeds instead")
    args = parser.parse_args(argv)
    if args.tune:
        return run(TUNING_SEEDS, tune=True)
    return run(args.seed_sweep or REPORT_SEEDS, tune=False)


if __name__ == "__main__":
    raise SystemExit(main())
