"""Command-line entry point for the detector evaluation.

    # score the committed default dataset
    python -m ml.run_eval

    # score a dataset somewhere else, and write the numbers out as JSON
    python -m ml.run_eval --data-dir path/to/out --json out/detector_scores.json

    # generate and score several datasets, to see how much the headline moves
    python -m ml.run_eval --seed-sweep 20260827 101 202 303

Run from the repository root.

The default dataset is `data/pipelines/synthetic/out`, which is gitignored, so the
first run needs:

    python -m data.pipelines.synthetic.generate
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from ml.evaluation.harness import describe_misses, evaluate, render, render_sweep

DEFAULT_DATA_DIR = Path("data/pipelines/synthetic/out")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_eval",
        description="Score the late-bloomer, fraud and duplicate detectors against "
        "the planted ground truth.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Generated dataset directory (default: {DEFAULT_DATA_DIR}).",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Also write the full report as JSON to this path.",
    )
    parser.add_argument(
        "--no-misses",
        action="store_true",
        help="Skip the per-case error analysis.",
    )
    parser.add_argument(
        "--seed-sweep",
        type=int,
        nargs="+",
        default=None,
        metavar="SEED",
        help="Generate a dataset per seed into a temporary directory and score each. "
        "Reports the spread of the headline F1.",
    )
    return parser


def _generate(seed: int, out_dir: Path) -> None:
    """Generate a dataset in-process rather than shelling out."""
    from data.pipelines.synthetic.config import GeneratorConfig
    from data.pipelines.synthetic.dataset import build_dataset
    from data.pipelines.synthetic.ground_truth import write as write_ground_truth
    from data.pipelines.synthetic.writer import export_json

    config = GeneratorConfig(seed=seed)
    dataset = build_dataset(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_ground_truth(dataset.ground_truth, out_dir / "ground_truth.json")
    export_json(dataset, out_dir)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.seed_sweep:
        reports = []
        with tempfile.TemporaryDirectory(prefix="northstar-sweep-") as tmp:
            for seed in args.seed_sweep:
                out_dir = Path(tmp) / str(seed)
                print(f"generating seed {seed} ...", file=sys.stderr)
                _generate(seed, out_dir)
                report = evaluate(out_dir)
                report.data_dir = f"generated, seed {seed}"
                reports.append(report)
                print(render(report))
                print()
        print(render_sweep(reports))
        return 0

    if not args.data_dir.exists():
        print(
            f"No dataset at {args.data_dir}.\nGenerate one first:\n"
            f"  python -m data.pipelines.synthetic.generate --out {args.data_dir}",
            file=sys.stderr,
        )
        return 1

    report = evaluate(args.data_dir)
    misses = None if args.no_misses else describe_misses(args.data_dir, report)
    print(render(report, misses=misses))

    if args.json:
        import json

        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = report.as_dict()
        payload["misses"] = misses or []
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\nwrote {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
