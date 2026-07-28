# Project status and handoff

Last updated: 2026-07-28. This is the "where we are, what to do next" page for anyone joining
or picking up the work. It is written for a teammate who has not seen the repo yet. For the
live task board see the NorthStar Delivery project (link in `CLAUDE.md`).

## Where the project is

The foundation and the core data layer are in place.

Done and verified:

- Monorepo scaffold (`apps/web`, `apps/api`, `packages/shared`, `data`, `ml`, `docs`,
  `docker`), README, `CLAUDE.md`.
- Docs: `docs/schema.md` (the data contract), `docs/architecture.md`, `docs/threat-model.md`,
  and the decisions log in `docs/decisions`.
- FastAPI backend (`apps/api`) with `/health` and `/health/db`, SQLAlchemy 2.0, Alembic wired.
- Next.js 14 web app (`apps/web`) landing page that pings the API.
- `docker-compose` stack (Postgres 16, api, web, ollama behind a profile), previously verified
  running end to end.
- **New: the eight core ORM models and the first migration.** All tables from `docs/schema.md`
  are implemented in `apps/api/app/models` (`Player`, `Organization`, `PlayerOrganization`,
  `Measurement`, `PerformanceEntry`, `User`, `Consent`, `AuditLog`), and
  `alembic/versions/0001_create_core_tables.py` creates them. See decision record
  `docs/decisions/0002-orm-models-and-first-migration.md` for the choices made.

The migration was validated without a live database (models rendered to DDL, and
`alembic upgrade head --sql` rendered clean SQL). It has not yet been applied to a running
Postgres. That is the first thing to do below.

## How to run it

```bash
cp .env.example .env
docker compose -f docker/docker-compose.yml up --build
```

To create the tables, run the migration inside the api container (or any environment with the
api dependencies and a reachable Postgres):

```bash
docker compose -f docker/docker-compose.yml exec api alembic upgrade head
```

Then sanity check:

- `alembic current` shows `0001_create_core_tables`.
- `alembic revision --autogenerate -m "check"` produces an **empty** migration (proves the
  models and the database agree). Delete that throwaway file afterward.

Web: http://localhost:3000. API: http://localhost:8000 (`/health`, `/health/db`).

## What to do next, in order

1. **Apply and confirm the migration** against a real Postgres, as above. This unblocks
   everyone. (Data engineering.)
2. **Synthetic data generator** in `data/pipelines/synthetic` using Faker, writing through the
   ORM models. Plant known ground-truth cases: late bloomers, fraud attempts, and duplicates,
   and record the ground truth so the detectors can be scored against it. This unblocks the ML
   track without waiting on the FootyStats subscription. (Data engineering, then ML.)
3. **Per-sport JSON schemas** in `packages/shared` for `PerformanceEntry.metrics`
   (`football@1`, `table_tennis@1`), plus the validation used on ingest. (Data engineering.)

## Known gaps to be aware of

These are deliberate deferrals, documented so a reviewer does not mistake them for bugs. Detail
is in `docs/decisions/0002-orm-models-and-first-migration.md`.

- Enum-like columns are plain text; intended values live in `app/models/enums.py`, not yet
  enforced by the database.
- `player_organization` overlap constraint, `audit_log` append-only enforcement, and the
  minor-guardian consent rule are not yet enforced at the database level.
- `pgvector` similarity storage is deferred until the ML workstream picks an embedding model.

## Per-track pointers

- **Data engineering**: `data/pipelines`, the models in `apps/api/app/models`, migration under
  `apps/api/alembic/versions`. Next: synthetic generator (task 2).
- **Intelligence / ML**: `ml`. Blocked on task 2 for training data; can design forecasting and
  detector harnesses against `docs/schema.md` in the meantime.
- **Security**: `docs/threat-model.md`, the `User`, `Consent`, and `AuditLog` models. Next:
  auth (JWT and password hashing) and RBAC over the role field.
- **Application**: `apps/web`. Next: role-based login and the coach dashboard against the API.
