"""Command-line entry point.

    python -m data.pipelines.synthetic.generate --out data/pipelines/synthetic/out
    python -m data.pipelines.synthetic.generate --database-url postgresql+psycopg://...

Run from the repository root. The default seed is committed in config.py, so two
people running the bare command get byte-identical data and can compare model
scores meaningfully.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import DEFAULT_SEED, GeneratorConfig
from .dataset import build_dataset
from .ground_truth import write as write_ground_truth
from .writer import export_json, verify_round_trip, write_to_database

DEFAULT_OUT = Path("data/pipelines/synthetic/out")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="synthetic",
        description="Generate the NorthStar synthetic evaluation dataset.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Random seed (default: {DEFAULT_SEED}). Same seed, same dataset.",
    )
    parser.add_argument(
        "--players",
        type=int,
        default=None,
        help="Population size. Planted case counts scale with it.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Directory for the JSON export and ground_truth.json (default: {DEFAULT_OUT}).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="If given, insert into this database through the ORM as well.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Delete existing rows before inserting. Only with --database-url.",
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="Skip the JSON export. ground_truth.json is always written.",
    )
    parser.add_argument(
        "--name-locale",
        default="ar_EG",
        help="Faker locale for player names (default: ar_EG).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    config = GeneratorConfig(seed=args.seed, name_locale=args.name_locale)
    if args.players:
        config = config.scaled(args.players)

    dataset = build_dataset(config)
    verify_round_trip(dataset)

    args.out.mkdir(parents=True, exist_ok=True)
    gt_path = write_ground_truth(dataset.ground_truth, args.out / "ground_truth.json")

    if not args.no_json:
        export_json(dataset, args.out)

    counts = dataset.counts()
    width = max(len(k) for k in counts)
    print(f"seed {config.seed}, {config.population.n_players} players requested")
    for key, value in counts.items():
        print(f"  {key.ljust(width)}  {value}")
    print("planted:")
    print(f"  late bloomers       {len(dataset.cases.late_bloomers)}")
    print(f"  fraud cases         {len(dataset.cases.fraud)}")
    print(f"  duplicate clusters  {len(dataset.cases.duplicates)}")
    print(f"answer key: {gt_path}")

    if args.database_url:
        inserted = write_to_database(dataset, args.database_url, truncate=args.truncate)
        print(f"inserted into database: {sum(inserted.values())} rows")

    return 0


if __name__ == "__main__":
    sys.exit(main())
