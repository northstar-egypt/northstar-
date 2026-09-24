"""Bring an empty database up to something worth looking at.

Runs once when the stack starts, then exits. Three steps:

  1. `alembic upgrade head`, so the schema matches the models.
  2. Generate the synthetic dataset and load it, **only if the database has no players**.
  3. Run the detectors and write their findings to the flag table.

Why step 2 is conditional
-------------------------
The obvious version truncates and regenerates on every boot. That would throw away every
decision a reviewer had made on the integrity board, every flag they had dismissed, and any
data a coach had entered, on nothing more than a restart. Seeding an empty database is
helpful; wiping a populated one because a container restarted is not.

To deliberately start over, take the volume with it:

    docker compose -f docker/docker-compose.yml down -v

Why step 3 runs every time
--------------------------
Writing flags is idempotent. Every flag carries a `dedupe_key`, so a case already raised is
recognised rather than duplicated, and a case somebody dismissed is not raised again. Running
it on each boot means a database seeded before the detectors existed catches up on the next
start.

This container is for local development and demos. It is not how data would reach a real
deployment, and it only ever writes synthetic rows.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
API_DIR = REPO / "apps" / "api"

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://northstar:northstar@db:5432/northstar"
)


def log(message: str) -> None:
    print(f"[seed] {message}", flush=True)


def run(command: list[str], cwd: Path | None = None) -> None:
    log("$ " + " ".join(command))
    result = subprocess.run(command, cwd=cwd, env={**os.environ, "DATABASE_URL": DATABASE_URL})
    if result.returncode != 0:
        raise SystemExit(f"[seed] failed: {' '.join(command)}")


def player_count() -> int:
    """How many players are already there. Decides whether to generate."""
    sys.path.insert(0, str(API_DIR))
    from sqlalchemy import create_engine, text

    engine = create_engine(DATABASE_URL, future=True)
    with engine.connect() as connection:
        return connection.execute(text("SELECT count(*) FROM player")).scalar_one()


def main() -> int:
    log(f"database: {DATABASE_URL.rsplit('@', 1)[-1]}")

    # 1. Schema.
    run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_DIR)

    # 2. Data. The generator always writes its JSON export, because step 3 reads it, and it
    #    only writes to the database when there is nothing there to lose.
    #
    #    Running it either way is free: the same seed produces byte-identical output, so the
    #    export written on a later boot describes exactly the rows already in the database.
    existing = player_count()
    generate = [sys.executable, "-m", "data.pipelines.synthetic.generate"]
    if existing:
        log(f"{existing} players already present, leaving the database alone")
        log("to start over: docker compose -f docker/docker-compose.yml down -v")
        log("writing the JSON export anyway, because the detector run reads it")
    else:
        log("empty database, generating and loading the synthetic dataset")
        generate += ["--database-url", DATABASE_URL, "--truncate"]
    run(generate, cwd=REPO)

    # 3. Flags. Idempotent, so it runs whatever happened above.
    log("running the detectors and writing flags")
    run(
        [sys.executable, "-m", "ml.write_flags", "--database-url", DATABASE_URL],
        cwd=REPO,
    )

    log("done. the stack has data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
