"""Command-line entry point for the professional age curves: the curves, and the test they can fail.

    python -m ml.run_age_curve_eval --cache-dir D:/northstar-data/footystats
    python -m ml.run_age_curve_eval --cache-dir D:/northstar-data/footystats --markdown

Run from the repository root. `--cache-dir` is a FootyStats cache made by
`python -m data.pipelines.footystats.fetch`; it must be outside the repository (real players).
Only the seven Premier League seasons are read, never Liga MX.

It prints, in order: what was read and what was left out and why; for each position group and
measure the curve (change per year of age, the curve with its 80% band, and the simple average by
age beside it); and the prediction test, with the sample sizes. `--markdown` prints the
prediction table in the form ml/README.md uses. The method and the rules are in
ml/pro/age_curves.py; the figure is `python -m ml.figure_age_curves`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ml.pro import age_curves as ac


def _signed(x: float) -> str:
    return f"{x:+.3f}"


def _interval(pair: tuple[float, float]) -> str:
    return f"{pair[0]:+.3f} to {pair[1]:+.3f}"


def print_data(records, report: ac.LoadReport) -> None:
    print("Data: Premier League seasons read from the FootyStats cache")
    for s in report.seasons:
        print(f"  {s['label']} (season id {s['season_id']}, {s['league']}): {s['rows']} rows, {s['used']} used")
    print(f"  rows read {report.rows_read}, used {report.used}, players {len({r.player_id for r in records})}")
    print("  left out:")
    for reason, count in report.left_out.items():
        print(f"    {reason}: {count}")


def print_curves(curves) -> None:
    print("\nCurves, all seasons read (change is per year of age, from age a to a + 1)")
    for (position, measure), (curve, simple) in curves.items():
        title = f"{position}, {ac.MEASURE_LABELS[measure]}"
        if curve is None:
            print(f"\n{title}: no age has {ac.MIN_PAIRS} pairs, nothing drawn")
            continue
        left = ", ".join(f"{a} ({n})" for a, n in sorted(curve.ages_left_out.items())) or "none"
        print(f"\n{title}: {curve.players} players, pairs by age below, ages left out for fewer than "
              f"{ac.MIN_PAIRS} pairs: {left}")
        print("  age  pairs  change   curve (80% band)           simple average (seasons)")
        for i, age in enumerate(curve.ages + [curve.ages[-1] + 1]):
            pairs = f"{curve.pairs[i]:>5}" if i < len(curve.ages) else "     "
            change = f"{curve.delta[i]:+.3f}" if i < len(curve.ages) else "      "
            avg = simple.get(age)
            avg_text = f"{avg[0]:.3f} ({avg[1]})" if avg else "not drawn"
            print(f"  {age:>3}  {pairs}  {change}  {curve.level[i]:.3f} ({curve.low[i]:.3f} to {curve.high[i]:.3f})"
                  f"   {avg_text}")


def print_prediction(results, markdown: bool) -> None:
    print("\nPrediction test: curves from pairs ending 2022/23 or earlier; predicts 2022/23 to 2023/24 "
          "and 2023/24 to 2024/25")
    print("MAE = mean absolute error of next season's value. Differences are curve minus baseline: "
          "negative means the curve is better. Intervals are 80%, resampling players.\n")
    head = ["Position", "Measure", "Scored", "Players", "Curve MAE", "Same as this season", "Position average",
            "Curve minus same", "Curve minus average"]
    rows = [[r.position, ac.MEASURE_LABELS[r.measure], str(r.n), str(r.players), f"{r.mae_curve:.3f}",
             f"{r.mae_same:.3f}", f"{r.mae_group:.3f}", _interval(r.curve_minus_same),
             _interval(r.curve_minus_group)] for r in results]
    if markdown:
        print("| " + " | ".join(head) + " |")
        print("| " + " | ".join(["---"] * len(head)) + " |")
        for row in rows:
            print("| " + " | ".join(row) + " |")
    else:
        widths = [max(len(head[i]), *(len(row[i]) for row in rows)) for i in range(len(head))]
        for row in [head] + rows:
            print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    skipped = {}
    for r in results:
        for reason, n in r.not_scored.items():
            skipped[reason] = skipped.get(reason, 0) + n
    print("\nPlayer pairs in the test seasons that could not be scored (a pair can count for several "
          "measures): " + ", ".join(f"{reason}: {n}" for reason, n in skipped.items()))


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="run_age_curve_eval", description=__doc__.splitlines()[0])
    parser.add_argument("--cache-dir", required=True, type=Path, help="a FootyStats cache outside the repository")
    parser.add_argument("--markdown", action="store_true", help="print the prediction table as markdown")
    parser.add_argument("--seed", type=int, default=0, help="the bootstrap seed")
    parser.add_argument("--bootstrap", type=int, default=ac.N_BOOTSTRAP, help="resamples for the bands")
    args = parser.parse_args(argv)

    records, report = ac.load_records(args.cache_dir)
    needed = {year for pair in ac.TEST_PAIRS for year in pair}
    missing = sorted(needed - {s["start_year"] for s in report.seasons})
    if missing:
        raise SystemExit(f"the cache has no Premier League season starting in {missing}; run the download "
                         "for season ids " + ", ".join(map(str, ac.PREMIER_LEAGUE_SEASON_IDS)))
    print_data(records, report)
    print_curves(ac.all_curves(records, n_bootstrap=args.bootstrap, seed=args.seed))
    results, _ = ac.evaluate_prediction(records, n_bootstrap=args.bootstrap, seed=args.seed)
    print_prediction(results, args.markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
