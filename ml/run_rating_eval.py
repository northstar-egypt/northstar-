"""Command-line entry point for the table tennis rating evaluation.

    # generate and score the reporting seeds (the numbers in ml/README.md)
    python -m ml.run_rating_eval

    # score other seeds
    python -m ml.run_rating_eval --seed-sweep 7 99

    # the tuning run: seeds 101, 202 and 303 only, over a grid of settings
    python -m ml.run_rating_eval --tune

    # what if strong players mostly met strong fields? (a what-if, never the default)
    python -m ml.run_rating_eval --schedule by-level

Run from the repository root. Each seed's dataset is generated in a temporary directory,
so this never reads a stale export. See ml/rating/evaluate.py for what is measured.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
from pathlib import Path

from data.pipelines.synthetic import performance
from ml.rating import evaluate as rating_eval
from ml.run_eval import _generate

REPORT_SEEDS = [20260827, 7, 99, 404, 555]
# Spread of the what-if schedule, in units of ability (one standard deviation is 0.28).
BY_LEVEL_SCALE = 0.15
TUNING_SEEDS = [101, 202, 303]


def _datasets(seeds: list[int], tmp: str) -> list[Path]:
    dirs = []
    for seed in seeds:
        out_dir = Path(tmp) / str(seed)
        print(f"generating seed {seed} ...", file=sys.stderr)
        _generate(seed, out_dir)
        dirs.append(out_dir)
    return dirs


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def _summary(reports: list[rating_eval.RatingReport]) -> str:
    out = [f"Across {len(reports)} seeds: mean of the per-seed numbers above"]
    genders = sorted({g.gender for r in reports for g in r.rankings})
    out.append(f"{'Spearman with hidden ability':30}" + "".join(f"{g:>12}" for g in genders))
    for method in rating_eval.RANKED:
        cells = []
        for gender in genders:
            rows = [g for r in reports for g in r.rankings if g.gender == gender]
            cells.append(f"{rating_eval._f(_mean(g.rho[method] for g in rows)):>12}")
        out.append(f"{method:30}" + "".join(cells))
    out.append("")
    out.append(f"{'display rule':30}" + "".join(f"{g:>12}" for g in genders))
    for method in rating_eval.MODELS:
        cells = []
        for gender in genders:
            rows = [g for r in reports for g in r.rankings if g.gender == gender]
            shown, total = sum(g.shown[method] for g in rows), sum(g.players for g in rows)
            cells.append(f"{f'{shown}/{total}':>12}")
        out.append(f"{method + ', shown':30}" + "".join(cells))
    out.append("")
    out.append(f"{'prediction':30}{'Brier':>8}{'log loss':>10}{'favourite won':>15}")
    for name in reports[0].predictions:
        scores = [r.predictions[name] for r in reports]
        out.append(
            f"{name:30}{_mean(s.brier for s in scores):>8.4f}"
            f"{_mean(s.log_loss for s in scores):>10.4f}"
            f"{_mean(s.favourite_won for s in scores):>15.3f}"
        )
    return "\n".join(out)


def _tune(dirs: list[Path]) -> None:
    """Grid search on the tuning seeds. Prints the tables; the constants are set by hand."""
    def loss(method: str, **kwargs) -> float:
        return _mean(rating_eval.evaluate(d, **kwargs).predictions[method].log_loss for d in dirs)

    print("Glicko-2 tau: mean log loss")
    for tau in (0.3, 0.5, 0.8, 1.2):
        print(f"  tau {tau:<5} {loss(rating_eval.GLICKO, tau=tau):.4f}")
    print("\npoint rating prior sd: mean log loss")
    for sd in (0.05, 0.1, 0.15, 0.2, 0.3, 0.5):
        print(f"  prior sd {sd:<5} {loss(rating_eval.POINTS, prior_sd=sd):.4f}")
    print("\nbaseline slopes: mean log loss")
    for slope in (1, 2, 3, 4, 6):
        print(f"  win rate slope {slope:<4} {loss(rating_eval.WIN_RATE, win_rate_slope=slope):.4f}")
    for slope in (10, 15, 20, 25, 30):
        print(f"  point rate slope {slope:<4} {loss(rating_eval.POINT_RATE, point_rate_slope=slope):.4f}")

    print("\ndisplay rules: players shown, and mean Spearman among them")
    for rd in (100, 110, 120, 130, 160):
        reports = [rating_eval.evaluate(d, show_max_rd=rd) for d in dirs]
        rows = [g for r in reports for g in r.rankings]
        shown = sum(g.shown[rating_eval.GLICKO] for g in rows)
        total = sum(g.players for g in rows)
        rho = _mean(g.rho_shown[rating_eval.GLICKO] for g in rows)
        print(f"  Glicko RD <= {rd:<5} shown {shown:>3}/{total}  rho {rating_eval._f(rho)}")
    for width in (0.04, 0.05, 0.06, 0.07, 0.08, 0.10):
        reports = [rating_eval.evaluate(d, show_max_point_range=width) for d in dirs]
        rows = [g for r in reports for g in r.rankings]
        shown = sum(g.shown[rating_eval.POINTS] for g in rows)
        total = sum(g.players for g in rows)
        rho = _mean(g.rho_shown[rating_eval.POINTS] for g in rows)
        print(f"  point range <= {width:<5} shown {shown:>3}/{total}  rho {rating_eval._f(rho)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_rating_eval", description=__doc__.splitlines()[0])
    parser.add_argument("--seed-sweep", type=int, nargs="+", default=None, metavar="SEED")
    parser.add_argument("--tune", action="store_true", help="Grid search on the tuning seeds.")
    parser.add_argument(
        "--schedule",
        choices=["by-age", "by-level"],
        default="by-age",
        help="Who meets whom. by-age is the generator's default; by-level is a what-if.",
    )
    args = parser.parse_args(argv)
    if args.schedule == "by-level":
        performance.TT_LEVEL_SCALE = BY_LEVEL_SCALE

    with tempfile.TemporaryDirectory(prefix="northstar-rating-") as tmp:
        if args.tune:
            _tune(_datasets(TUNING_SEEDS, tmp))
            return 0
        seeds = args.seed_sweep or REPORT_SEEDS
        overlap = sorted(set(seeds) & set(TUNING_SEEDS))
        if overlap:
            print(f"note: seeds {overlap} are tuning seeds; do not report them", file=sys.stderr)
        reports = []
        for d in _datasets(seeds, tmp):
            report = rating_eval.evaluate(d)
            report.data_dir = f"generated, seed {d.name}"
            reports.append(report)
            print(rating_eval.render(report))
            print()
        print(_summary(reports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
