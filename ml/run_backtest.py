"""Command-line entry point for the late-bloomer backtest.

    # the default dataset
    python -m ml.run_backtest

    # the five reported seeds, pooled, as generated and with simulated release at 14
    python -m ml.run_backtest --seed-sweep 20260827 7 99 404 555
    python -m ml.run_backtest --seed-sweep 20260827 7 99 404 555 --attrition

    # real data: export the local database first, then point at the export
    python -m ml.export_db --out out/real
    python -m ml.run_backtest --data-dir out/real

Run from the repository root. See `ml/backtest.py` for what is measured and why.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from ml.backtest import render, run
from ml.run_eval import DEFAULT_DATA_DIR


def _generate(seed: int, out_dir: Path, *, attrition: bool, players: int | None) -> None:
    from data.pipelines.synthetic.config import GeneratorConfig
    from data.pipelines.synthetic.dataset import build_dataset
    from data.pipelines.synthetic.ground_truth import write as write_ground_truth
    from data.pipelines.synthetic.writer import export_json

    config = GeneratorConfig(seed=seed, attrition=attrition)
    if players:
        config = config.scaled(players)
    dataset = build_dataset(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_ground_truth(dataset.ground_truth, out_dir / "ground_truth.json")
    export_json(dataset, out_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_backtest", description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--seed-sweep", type=int, nargs="+", default=None, metavar="SEED")
    parser.add_argument(
        "--attrition",
        action="store_true",
        help="With --seed-sweep: generate with simulated release at 14.",
    )
    parser.add_argument(
        "--players",
        type=int,
        default=None,
        help="With --seed-sweep: population per dataset (default 212). Planted cases scale "
        "with it. Use a larger one to measure an effect too small to see at 212.",
    )
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--no-misses", action="store_true")
    args = parser.parse_args(argv)

    if args.seed_sweep:
        reports = []
        with tempfile.TemporaryDirectory(prefix="northstar-backtest-") as tmp:
            for seed in args.seed_sweep:
                print(f"generating seed {seed} ...", file=sys.stderr)
                out_dir = Path(tmp) / str(seed)
                _generate(seed, out_dir, attrition=args.attrition, players=args.players)
                reports.append(run(out_dir))
        label = "with simulated release at 14" if args.attrition else "as generated"
        size = f"{args.players} players each" if args.players else "212 players each"
        title = (
            f"Late-bloomer backtest, seeds {', '.join(map(str, args.seed_sweep))}, "
            f"{size}, pooled, {label}"
        )
    else:
        if not args.data_dir.exists():
            print(f"No dataset at {args.data_dir}.", file=sys.stderr)
            return 1
        reports = [run(args.data_dir)]
        title = f"Late-bloomer backtest, {args.data_dir}"

    print(render(reports, title, misses=not args.no_misses))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps([r.as_dict() for r in reports], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
