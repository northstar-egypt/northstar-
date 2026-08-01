# Project status and handoff

Last updated: 2026-08-01. This is the "where we are, what to do next" page for anyone joining
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
- **The eight core ORM models and the first migration.** All tables from `docs/schema.md`
  are implemented in `apps/api/app/models` (`Player`, `Organization`, `PlayerOrganization`,
  `Measurement`, `PerformanceEntry`, `User`, `Consent`, `AuditLog`), and
  `alembic/versions/0001_create_core_tables.py` creates them. See decision record
  `docs/decisions/0002-orm-models-and-first-migration.md` for the choices made.
- **New: org teams and review routing.** Four teams exist in the `northstar-egypt` org, one
  per workstream, each with write access to the repo. `.github/CODEOWNERS` maps directories
  to those teams, so opening a pull request automatically requests a review from the people
  who own that area. See "Who owns what" below.

The migration has been applied and verified against a real Postgres 16 running under
`docker compose`. `alembic upgrade head` ran clean, all eight tables were created, and a
fresh `alembic revision --autogenerate` produced an empty migration, which proves the models
and the live database schema agree.

## How to run it

```bash
cp .env.example .env
docker compose -f docker/docker-compose.yml up --build
```

Your database starts empty. Create the tables by running the migration inside the api
container (or any environment with the api dependencies and a reachable Postgres):

```bash
docker compose -f docker/docker-compose.yml exec api alembic upgrade head
```

Then sanity check:

- `alembic current` shows `0001_create_core_tables`.
- `alembic revision --autogenerate -m "check"` produces an **empty** migration (proves the
  models and the database agree). Delete that throwaway file afterward.

Web: http://localhost:3000. API: http://localhost:8000 (`/health`, `/health/db`).

## Who owns what

Four teams in the `northstar-egypt` org, one per workstream, all with write access to the
repo. `.github/CODEOWNERS` routes reviews to them automatically.

| Team | Owns |
| --- | --- |
| `@northstar-egypt/data` | `data/`, `apps/api/`, the models and migrations, docs, docker |
| `@northstar-egypt/ml` | `ml/`, and `packages/shared` alongside the others |
| `@northstar-egypt/security` | the threat model, and the models and migrations alongside data |
| `@northstar-egypt/app` | `apps/web/` |

Shared surfaces have more than one owner on purpose. The ORM models and migrations are the
contract every track builds on, and `User`, `Consent`, and `AuditLog` live there, so security
reviews them too. `packages/shared` is the contract between the data layer, ML, and the
frontend, so all three review it.

Reviews are requested, not required. There is no branch protection rule on `main` yet. That
is a call for the team to make once several people are contributing regularly.

## Working agreement

- Branch off `main`, one branch per task, named `feat/...`, `fix/...`, `chore/...`, or
  `docs/...`.
- Open a pull request. Code owners get requested automatically. Do not merge your own work
  on the shared core (models, migrations, `packages/shared`) without a second pair of eyes.
- Conventional Commits for messages: `feat(api): ...`, `docs: ...`, `chore: ...`.
- Move your task on the NorthStar Delivery board when you start it and when you finish it.
  The board is the record of progress that the team and the TA read.

## What to do next, in order

1. **Synthetic data generator** in `data/pipelines/synthetic` using Faker, writing through the
   ORM models. Plant known ground-truth cases: late bloomers, fraud attempts, and duplicates,
   and record the ground truth so the detectors can be scored against it. This unblocks the ML
   track without waiting on the FootyStats subscription. (Data engineering, then ML.)
2. **Per-sport JSON schemas** in `packages/shared` for `PerformanceEntry.metrics`
   (`football@1`, `table_tennis@1`), plus the validation used on ingest. The files in
   `packages/shared/schemas` today are illustrative drafts and are not enforced anywhere yet.
   (Data engineering.)

These two are sequential because the generator produces the metrics the schemas describe.
Everything in the per-track list below can start in parallel with them, today.

## Known gaps to be aware of

These are deliberate deferrals, documented so a reviewer does not mistake them for bugs. Detail
is in `docs/decisions/0002-orm-models-and-first-migration.md`.

- Enum-like columns are plain text; intended values live in `app/models/enums.py`, not yet
  enforced by the database.
- `player_organization` overlap constraint, `audit_log` append-only enforcement, and the
  minor-guardian consent rule are not yet enforced at the database level.
- `pgvector` similarity storage is deferred until the ML workstream picks an embedding model.

## Per-track pointers

Each of these can be picked up now. None of them are blocked on the two tasks above.

- **Data engineering**: `data/pipelines`, the models in `apps/api/app/models`, migration under
  `apps/api/alembic/versions`. Next: the synthetic generator (task 1). Also unblocked and
  independent: add `data/pipelines/requirements.txt` for the heavy deps (pandas, Faker,
  Playwright) so they stay out of the lean API image.
- **Intelligence / ML**: `ml`. No training data yet, but the evaluation harness does not need
  it. Build the walk-forward validation harness and the two baselines we are graded against
  (last value, population average) so that the moment synthetic data lands, forecasts can be
  scored. Read `docs/schema.md` for the shapes to expect.
- **Security**: `docs/threat-model.md`, the `User`, `Consent`, and `AuditLog` models. Next:
  decide the authentication approach and write it up as a decision record in
  `docs/decisions`, then implement JWT and password hashing and RBAC over the role field.
  The decision write-up needs no code and is a good first task.
- **Application**: `apps/web`. Next: wireframe the six or seven main screens (this needs no
  code either), then role-based login and the coach dashboard against the API.
