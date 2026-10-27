"""Bring an empty database up to something worth looking at.

Runs once when the stack starts, then exits. Five steps:

  1. `alembic upgrade head`, so the schema matches the models.
  2. Generate the synthetic dataset and load it, **only if the database has no players**,
     dated up to the day before it is loaded (`--reference-date`), so its readings are recent.
  3. Run the detectors on the database and write their findings to the flag table.
  4. Add synthetic tagged match events from the match records, once (for the shot map).
  5. Set the governorate of synthetic clubs that have none (coverage by governorate).
  6. Add three seasons of a synthetic Egyptian league, once (the pro tier, decision 0003).

Why step 2 is conditional
-------------------------
The obvious version truncates and regenerates on every boot. That would throw away every
decision a reviewer had made on the integrity board, every flag they had dismissed, and any
data a coach had entered, on nothing more than a restart. Seeding an empty database is
helpful; wiping a populated one because a container restarted is not.

To deliberately start over, delete the database volume only:

    docker compose -f docker/docker-compose.yml down
    docker volume rm docker_pgdata

(`down -v` also deletes `docker_ollama-data`, the downloaded language models, several GB.)

Why the data is dated to the day before it is loaded
----------------------------------------------------
The generator dates everything relative to a reference day so its runs reproduce, and the
evaluation datasets keep the default (2026-06-30). The demo database used it too, so months
later every player looked unmeasured and the oversight screen read 100% stale. Loaded with
yesterday as the reference, the readings are as recent as the generator makes them on its own
reference day, and they age from then on, as real records would. Yesterday rather than today,
so nothing generated shares a day with a reading a coach enters on the day of loading.

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
from datetime import date, timedelta
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

    # 2. Data, only when there is nothing there to lose.
    existing = player_count()
    if existing:
        log(f"{existing} players already present, leaving the database alone")
        log("to start over: docker compose -f docker/docker-compose.yml down, "
            "then docker volume rm docker_pgdata")
    else:
        # Up to yesterday, not today: a reading a coach enters on the day of loading (the
        # demo does) must be the newest, not share a day with a generated one. Two readings of
        # one measure on one day are a conflict a merge settles in the kept record's favour.
        reference = (date.today() - timedelta(days=1)).isoformat()
        log(f"empty database, generating and loading the synthetic dataset, dated up to {reference}")
        run(
            [sys.executable, "-m", "data.pipelines.synthetic.generate",
             "--database-url", DATABASE_URL, "--truncate", "--reference-date", reference],
            cwd=REPO,
        )

    # 3. Flags, from the database itself, so they cover whatever is there now (players added
    #    since, and data loaded on another day). Idempotent, so it runs on every boot.
    log("running the detectors on the database and writing flags")
    run(
        [sys.executable, "-m", "ml.write_flags", "--from-database", "--database-url", DATABASE_URL],
        cwd=REPO,
    )

    # 4. Tagged match events, made from the match records so the shot map has something to
    #    show (data/pipelines/synthetic/tagged_events.py). Added once, and to a database that
    #    already had players too, which step 2 never touches.
    log("adding synthetic tagged match events, once")
    run(
        [sys.executable, "-m", "data.pipelines.synthetic.tagged_events", "--database-url", DATABASE_URL],
        cwd=REPO,
    )

    # 6 (before 5, so the league's new clubs get a governorate too). Three seasons of a
    #    synthetic Egyptian league, shaped like FootyStats' data: the pro tier's records until
    #    the subscription is live (data/pipelines/synthetic/pro_league.py). Once.
    log("adding a synthetic Egyptian league, once")
    run(
        [sys.executable, "-m", "data.pipelines.synthetic.pro_league", "--database-url", DATABASE_URL],
        cwd=REPO,
    )

    # 5. The governorate of each synthetic club and academy, for coverage by governorate
    #    (data/pipelines/synthetic/regions.py). Only rows with none yet, so it runs every boot.
    log("setting the governorate of synthetic clubs that have none")
    run(
        [sys.executable, "-m", "data.pipelines.synthetic.backfill_regions", "--database-url", DATABASE_URL],
        cwd=REPO,
    )

    log("done. the stack has data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
