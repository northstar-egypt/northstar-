# NorthStar API

FastAPI backend. Serves the web app, owns all data access, enforces access control, and
orchestrates the ML and LLM layers. SQLAlchemy 2.0 for models, Alembic for migrations.

## Layout

```
app/
  main.py        FastAPI app, CORS, router mounting
  config.py      env-driven settings (pydantic-settings)
  db.py          engine, session factory, declarative Base, get_db dependency
  deps.py        who is calling. No real auth yet, see below
  models/        ORM models for the shared core schema
  schemas/       response shapes, mirroring apps/web/lib/types.ts
  services/      access control, cohort statistics, view assembly
  routers/       API routers
tests/           pytest suite, needs a live PostgreSQL
alembic/         migration environment and versions
alembic.ini      Alembic config (DB URL comes from the environment, not this file)
requirements.txt pinned dependencies
requirements-dev.txt  test-only dependencies, never installed into the image
Dockerfile       Python 3.11 slim image
```

## Run with Docker (recommended)

From the repo root:

```bash
docker compose -f docker/docker-compose.yml up --build api
```

The API comes up on http://localhost:8000. `GET /docs` has the interactive documentation.

| Endpoint | What it serves |
| --- | --- |
| `GET /health`, `GET /health/db` | liveness and database reachability, no caller needed |
| `GET /me` | the resolved caller |
| `GET /players` | the coach squad table, scoped to the caller |
| `GET /players/{id}/profile` | the full player profile, filtered for role and consent |
| `POST /search` | scout search, filters only |
| `GET /compare?players=a,b` | two to four players side by side |
| `GET /oversight?sport=football` | federation aggregates, counts only |
| `GET /integrity/flags` | the review queue: fraud, duplicate and anomaly |
| `POST /integrity/flags/{id}/decision` | record a decision, with its reason |
| `GET /dev/identities` | development only, accounts the role switcher can act as |

Write endpoints for player data (`POST /players`, `POST /players/{id}/measurements`) are not
built yet.

## Flags

Flags come from the `flag` table, written by a batch job, not computed inside a request. A
flag has state (open, confirmed, dismissed, needs_info, plus who decided and why), the
detectors read the JSON export rather than the database, and running three detectors over the
whole population inside a page load is the wrong shape at any scale.

To populate them:

```bash
python -m data.pipelines.synthetic.generate --database-url $DATABASE_URL --truncate
python -m ml.write_flags
```

Safe to rerun. Every flag carries a `dedupe_key`, so a case already raised is recognised
rather than duplicated and a case a reviewer dismissed is not raised again. See
`docs/schema.md` for what that key does and does not cover.

Deciding a flag writes three things: the new status, an append-only `flag_event` saying who
decided what and why, and an `audit_log` row. The reason is required, and that is not
bureaucracy: each decision plus its reason is a labelled example, and labelled examples are
what the detectors' precision and recall are computed from.

## Authentication: there is none yet

The auth approach is an open decision on the project board, so rather than pick one, the API
resolves a caller from a request header:

```bash
curl -H "X-NorthStar-User: coach.001@northstar.test" http://localhost:8000/players
```

This is honoured **only** when `ENVIRONMENT=development`. Anywhere else every endpoint that
needs a caller returns 401, because no other identity source exists. Anyone who can reach the
API in development can act as any user including an admin, which is fine for a local stack of
synthetic data and is not fine for anything else. `GET /dev/identities` lists one account per
role so you do not have to go digging in psql.

When real sessions land, `app/deps.py::current_user` is the only function that changes.
Everything downstream takes a caller and does not care where it came from.

## Access control

All of it is in `app/services/access.py`, deliberately one file so it can be read in one
sitting. The rules come from `docs/schema.md` and `docs/threat-model.md`:

- **coach** sees and edits players in their own organization. A coach with no organization
  sees nobody, because failing closed surfaces a broken account instead of leaking a squad.
- **scout** reads across the population but **cannot see a minor without a current
  `scouting_visibility` consent**. In search those players come back marked `withheld` with
  the name and date of birth stripped, so the screen renders a locked card.
- **federation** and **admin** read broadly. Only admins edit.
- **player** sees only their own record, and does not see model flags about themselves.

Two behaviours worth knowing before changing anything here:

A player the caller may not see returns **404, not 403**. A distinguishable status code tells
an unauthorised caller that the player exists, which for a child without scouting consent is
exactly the disclosure the rule exists to prevent.

Whether a blocked minor should appear as a locked card or not at all is still an open team
decision (`docs/wireframes/README.md`). The wireframe drew the locked card, so that is what
this implements, and the alternative is one filter in the search router.

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
docker compose -f ../../docker/docker-compose.yml up -d db
pytest tests
```

The suite needs a real PostgreSQL. The models use JSONB, ARRAY and `gen_random_uuid()`, so
SQLite would mean testing a different schema from the one that runs. With no database
reachable it skips with a message rather than failing. Each test runs in a transaction that
is rolled back, so it is safe to run against a database holding the synthetic dataset.

`tests/test_access_control.py` is the start of the graded RBAC deliverable.

## Run without Docker

Needs Python 3.11 and a reachable PostgreSQL. From `apps/api`:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://northstar:northstar@localhost:5432/northstar
uvicorn app.main:app --reload
```

## Migrations

Once the ORM models exist, generate and apply migrations:

```bash
alembic revision --autogenerate -m "create core tables"
alembic upgrade head
```

The URL Alembic uses comes from the same `DATABASE_URL` the app reads, so there is one
source of truth. New models must be imported in `app/models/__init__.py` or autogenerate
will not see them.

## Conventions

- Keep `main.py` thin. Logic lives in routers and services.
- Every model is imported in `app/models/__init__.py` so migrations and metadata see it.
- Pin new dependencies in `requirements.txt`.
