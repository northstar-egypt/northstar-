"""Save the demo database once, and put it back in one command (docs/demo.md).

    python docker/demo_snapshot.py save              # after demo_check.py says ready
    python docker/demo_snapshot.py restore           # before presenting, or after a rehearsal
    python docker/demo_snapshot.py list

Resetting from the generator (docs/demo.md, "After a rehearsal") takes minutes and gives a new
dataset, dated from the day it is loaded, so the demo player's date of birth changes. A
snapshot gives back exactly the database that was checked, in well under a minute, with no
rebuild. Use it between rehearsals and on the day.

It runs `pg_dump` and `pg_restore` inside the `northstar-db` container, so nothing but Docker
and Python is needed. Restoring stops the API, replaces the `northstar` database, and starts
the API again; Ollama and its downloaded models are not touched, and neither is the database
volume.

Snapshots are written to `docker/snapshots/`, which git ignores. The data in them is
synthetic, but a database dump never becomes a commit (CLAUDE.md). The summaries the models
wrote are held in the API's memory, not the database, so run `python tests/e2e/demo_check.py`
after a restore: it warms the models and writes the demo player's summary again.

A snapshot ages like the data in it: the readings in a snapshot saved weeks before the demo
look weeks old. Save it within a few days of presenting.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SNAPSHOTS = Path(__file__).resolve().parent / "snapshots"
DB_CONTAINER = "northstar-db"
API_CONTAINER = "northstar-api"
USER = DATABASE = "northstar"


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=False, **kwargs)


def _path(name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        sys.exit(f"a snapshot name is letters, digits, - and _ only: {name!r}")
    return SNAPSHOTS / f"{name}.dump"


def _db_is_up() -> None:
    done = _run(["docker", "exec", DB_CONTAINER, "pg_isready", "-U", USER], capture_output=True)
    if done.returncode != 0:
        sys.exit(
            f"the {DB_CONTAINER} container is not running. Start it with:\n"
            "  docker compose -f docker/docker-compose.yml up -d db"
        )


def save(name: str) -> None:
    _db_is_up()
    SNAPSHOTS.mkdir(exist_ok=True)
    target = _path(name)
    partial = target.with_suffix(".partial")
    with partial.open("wb") as out:
        done = _run(
            ["docker", "exec", DB_CONTAINER, "pg_dump", "-U", USER, "-d", DATABASE, "-Fc"],
            stdout=out,
        )
    if done.returncode != 0:
        partial.unlink(missing_ok=True)
        sys.exit("pg_dump failed; the message is above. Nothing was saved.")
    partial.replace(target)
    print(f"saved {target.relative_to(Path.cwd()) if target.is_relative_to(Path.cwd()) else target}"
          f" ({target.stat().st_size / 1e6:.1f} MB)")


def restore(name: str) -> None:
    source = _path(name)
    if not source.exists():
        sys.exit(f"no snapshot named {name!r}. Saved ones: {', '.join(_names()) or 'none'}")
    _db_is_up()
    started = time.monotonic()
    print(f"stopping {API_CONTAINER}, so nothing writes while the database is replaced")
    _run(["docker", "stop", API_CONTAINER], capture_output=True)
    try:
        for sql in (
            f"DROP DATABASE IF EXISTS {DATABASE} WITH (FORCE)",
            f"CREATE DATABASE {DATABASE} OWNER {USER}",
        ):
            done = _run(["docker", "exec", DB_CONTAINER, "psql", "-U", USER, "-d", "postgres",
                         "-v", "ON_ERROR_STOP=1", "-q", "-c", sql])
            if done.returncode != 0:
                sys.exit(f"could not run: {sql}")
        with source.open("rb") as dump:
            done = _run(
                ["docker", "exec", "-i", DB_CONTAINER, "pg_restore", "-U", USER, "-d", DATABASE,
                 "--no-owner", "--exit-on-error"],
                stdin=dump,
            )
        if done.returncode != 0:
            sys.exit("pg_restore failed; the message is above. Run restore again, or reset from "
                     "the generator (docs/demo.md, After a rehearsal).")
    finally:
        _run(["docker", "start", API_CONTAINER], capture_output=True)
    print(f"restored {name} in {time.monotonic() - started:.0f} s; {API_CONTAINER} started again")
    print("next: python tests/e2e/demo_check.py  (warms the models and the demo player's summary)")


def _names() -> list[str]:
    return sorted(p.stem for p in SNAPSHOTS.glob("*.dump"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("save", "restore", "list"))
    parser.add_argument("name", nargs="?", default="demo", help="default: demo")
    args = parser.parse_args()
    if args.action == "save":
        save(args.name)
    elif args.action == "restore":
        restore(args.name)
    else:
        for name in _names():
            path = _path(name)
            when = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            print(f"{name:20} saved {when}  {path.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
