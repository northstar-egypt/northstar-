"""Command-line entry point for the height forecast evaluation.

    # score the default dataset
    python -m ml.run_forecast_eval

    # write the numbers out as JSON as well
    python -m ml.run_forecast_eval --json out/forecast_scores.json

    # generate and score several datasets, to see how much the headline moves
    python -m ml.run_forecast_eval --seed-sweep 20260827 7 99 404 555

Run from the repository root. Like `ml.run_eval`, the default dataset is gitignored, so the
first run needs `python -m data.pipelines.synthetic.generate`.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from ml import challengers
from ml.forecasting.models import FORECASTERS
from ml.forecasting.walk_forward import evaluate, render, render_sweep
from ml.run_eval import DEFAULT_DATA_DIR, _generate


def _forecasters(include_challengers: bool) -> dict:
    """The core four, plus the XGBoost challenger when it is installed and wanted."""
    if include_challengers and challengers.available():
        from ml.challengers.xgb_forecast import FORECASTERS as XGBOOST

        return {**FORECASTERS, **XGBOOST}
    if include_challengers:
        print(
            "Challengers skipped: install ml/requirements.txt for xgboost.", file=sys.stderr
        )
    return dict(FORECASTERS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_forecast_eval",
        description="Walk-forward MAE and RMSE of the height forecasters against the "
        "last-value and population-average baselines.",
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--seed-sweep", type=int, nargs="+", default=None, metavar="SEED")
    parser.add_argument(
        "--no-challengers",
        action="store_true",
        help="Score only the four v1 forecasters, without the XGBoost challenger.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    forecasters = _forecasters(not args.no_challengers)

    if args.seed_sweep:
        reports = []
        with tempfile.TemporaryDirectory(prefix="northstar-forecast-") as tmp:
            for seed in args.seed_sweep:
                out_dir = Path(tmp) / str(seed)
                print(f"generating seed {seed} ...", file=sys.stderr)
                _generate(seed, out_dir)
                report = evaluate(out_dir, forecasters)
                report.data_dir = f"generated, seed {seed}"
                reports.append(report)
                print(render(report))
                print()
        print(render_sweep(reports))
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(
                json.dumps([r.as_dict() for r in reports], indent=2) + "\n", encoding="utf-8"
            )
        return 0

    if not args.data_dir.exists():
        print(
            f"No dataset at {args.data_dir}.\nGenerate one first:\n"
            f"  python -m data.pipelines.synthetic.generate --out {args.data_dir}",
            file=sys.stderr,
        )
        return 1

    report = evaluate(args.data_dir, forecasters)
    print(render(report))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
