"""Command-line entry point for the scouting report's validity check.

    # the reporting seeds (the numbers in ml/README.md, "Scouting report")
    python -m ml.run_report_eval

    # other seeds
    python -m ml.run_report_eval --seed-sweep 101 202 303

Run from the repository root. See ml/pro/report_eval.py for what is measured. There is no
tuning run: the report's thresholds were fixed before this was first run.
"""

from __future__ import annotations

import argparse
import statistics
import sys

from ml.pro import report_eval
from ml.sport_modules import registry

REPORT_SEEDS = [20260827, 7, 99, 404, 555]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_report_eval", description=__doc__.splitlines()[0])
    parser.add_argument("--seed-sweep", type=int, nargs="+", help="score these seeds instead")
    args = parser.parse_args(argv)
    seeds = args.seed_sweep or REPORT_SEEDS
    module = registry()["football"]
    results = []
    for seed in seeds:
        print(f"building league for seed {seed} ...", file=sys.stderr)
        results.append(report_eval.evaluate(seed, module))

    groups = sorted({g for r in results for g in r.by_group})
    print(f"Scouting report level against true quality, seeds {seeds}")
    print(f"{'position group':24}" + "".join(f"{s:>10}" for s in seeds) + f"{'mean':>10}")
    for group in groups:
        values = [r.by_group.get(group) for r in results]
        known = [v for v in values if v is not None]
        print(f"{group:24}" + "".join(f"{v:>10.2f}" if v is not None else f"{'n/a':>10}" for v in values)
              + f"{statistics.fmean(known):>10.2f}")
    overall = [v for r in results for v in r.by_group.values() if v is not None]
    print(f"{'all groups (mean)':24}" + " " * 10 * len(seeds) + f"{statistics.fmean(overall):>10.2f}")
    print()
    print(f"Baseline: minutes played against true quality, seeds {seeds}")
    for group in groups:
        values = [r.minutes_by_group.get(group) for r in results]
        known = [v for v in values if v is not None]
        print(f"{group:24}" + "".join(f"{v:>10.2f}" if v is not None else f"{'n/a':>10}" for v in values)
              + f"{statistics.fmean(known):>10.2f}")
    base = [v for r in results for v in r.minutes_by_group.values() if v is not None]
    print(f"{'all groups (mean)':24}" + " " * 10 * len(seeds) + f"{statistics.fmean(base):>10.2f}")
    print(f"\nreports: {sum(r.reports for r in results)} over {len(seeds)} leagues")

    print("\nRecommendations, summed over seeds (chance alone: a third)")
    for name, meaning in (("Shortlist", "in the top third of true quality"),
                          ("Not now", "in the bottom third of true quality"), ("Monitor", None)):
        n = sum(r.recommendations[name][0] for r in results)
        hit = sum(r.recommendations[name][1] for r in results)
        if meaning:
            print(f"  {name:10} {n:>5} players, {hit} {meaning} ({hit / max(1, n):.0%})")
        else:
            print(f"  {name:10} {n:>5} players")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
