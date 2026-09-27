"""Export the database to the JSON files the ML harnesses read.

    python -m ml.export_db --out out/db_export
    python -m ml.run_backtest --data-dir out/db_export

This is how the backtest and the forecast evaluation run on real data. They read the same
five files the synthetic generator writes (players, measurements, performance_entries,
organizations, affiliations), keyed by the ORM attribute names, so nothing downstream knows
or cares where the rows came from. There is no ground_truth.json in a database export, and the
harnesses report what they can measure without one.

This writes real player data to disk
------------------------------------
On a machine holding real data, the output of this command is real data about real children.
CLAUDE.md is absolute about it never reaching the repository, so the command refuses to write
to any path inside the repository that git would track. `out/` at the repository root is
gitignored and is the intended place. A path outside the repository is allowed and is the
user's responsibility.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ml.write_flags import DEFAULT_DATABASE_URL, _bootstrap_api_path

REPO_ROOT = Path(__file__).resolve().parents[1]


def tracked_by_git(path: Path) -> bool:
    """True if a file written at `path` could be committed.

    Asks git rather than reimplementing .gitignore matching. A probe file name is checked
    because git answers for paths, and the directory may not exist yet. Fails closed: if git
    cannot answer, the path is treated as trackable.
    """
    path = path.resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError:
        return False
    probe = path / "players.json"
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(probe)],
            cwd=REPO_ROOT,
            capture_output=True,
        )
    except OSError:
        return True
    # 0 means ignored, 1 means not ignored, anything else is an error.
    return result.returncode != 0


def export(database_url: str, out_dir: Path) -> dict[str, int]:
    _bootstrap_api_path()

    from sqlalchemy import create_engine, inspect, select
    from sqlalchemy.orm import Session

    from app.models.measurement import Measurement
    from app.models.organization import Organization
    from app.models.performance_entry import PerformanceEntry
    from app.models.player import Player
    from app.models.player_organization import PlayerOrganization

    from data.pipelines.synthetic.writer import _json_default

    tables = {
        "players": Player,
        "measurements": Measurement,
        "performance_entries": PerformanceEntry,
        "organizations": Organization,
        "affiliations": PlayerOrganization,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    engine = create_engine(database_url, future=True)
    with Session(engine) as session:
        for name, model in tables.items():
            keys = [attr.key for attr in inspect(model).column_attrs]
            rows = [
                {key: getattr(row, key) for key in keys}
                for row in session.execute(select(model)).scalars()
            ]
            (out_dir / f"{name}.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=2, default=_json_default) + "\n",
                encoding="utf-8",
            )
            counts[name] = len(rows)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="export_db", description=__doc__.split("\n")[0])
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if tracked_by_git(args.out):
        print(
            f"Refusing to write to {args.out}: git would track files there, and this export "
            f"may be real player data. Use out/ at the repository root, which is gitignored, "
            f"or a directory outside the repository.",
            file=sys.stderr,
        )
        return 2

    counts = export(args.database_url, args.out)
    for name, count in counts.items():
        print(f"  {name:20} {count:>7}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
