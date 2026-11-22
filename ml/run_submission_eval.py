"""Command-line entry point for grading the diaspora submission checks (decision 0011).

    # the reporting seeds (the numbers in ml/README.md, "Diaspora submission checks")
    python -m ml.run_submission_eval

    # the calibration seeds 101, 202 and 303 (run while building; nothing is tuned)
    python -m ml.run_submission_eval --tune

Run from the repository root. Each register is generated in memory from its seed. See
ml/submission_eval.py for what is planted and measured.
"""

from __future__ import annotations

import argparse
import sys

from ml import submission_eval


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=int, nargs="+", default=None)
    parser.add_argument("--tune", action="store_true", help="the calibration seeds 101, 202 and 303")
    parser.add_argument("--players", type=int, default=submission_eval.PLAYERS)
    args = parser.parse_args(argv)
    seeds = args.seeds or (submission_eval.CALIBRATION if args.tune else submission_eval.REPORTED)
    results = []
    for seed in seeds:
        print(f"seed {seed} ...", file=sys.stderr, flush=True)
        results.append(submission_eval.evaluate_seed(seed, args.players))
    print(submission_eval.render(submission_eval.summarise(results)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
