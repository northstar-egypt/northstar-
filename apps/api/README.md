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
| `GET /dev/identities` | development only, one demo account per role for the login screen |

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

## Authentication

Email and password, checked against an argon2id hash, start a session: a signed token (JWT)
in an **HttpOnly, SameSite=Lax** cookie that page scripts cannot read. Every request re-checks
the token and reloads the account from the database, so a deactivated account or a changed
role applies at once. The design, the threats it answers and its known gaps are in
`docs/threat-model.md` under "Authentication and sessions".

| Endpoint | What it does |
| --- | --- |
| `POST /auth/login` | checks `{email, password}`, sets the session cookie, returns who signed in |
| `POST /auth/logout` | clears the cookie |
| `GET /me` | who the session belongs to, 401 when signed out |

From a script or curl, sign in once and reuse the cookie:

```bash
curl -c jar.txt -H "Content-Type: application/json" \
  -d '{"email":"coach.001@northstar.test","password":"northstar-demo"}' \
  http://localhost:8000/auth/login
curl -b jar.txt http://localhost:8000/players
```

Every synthetic account's password is `northstar-demo`, published on purpose because the data
is synthetic. `GET /dev/identities` (development only) lists one account per role for the
login screen's demo buttons, which sign in through the same `POST /auth/login`.

Configuration: `JWT_SECRET` signs the tokens. The development default is public, so outside
`ENVIRONMENT=development` the API refuses to start unless it is set to at least 32 random
characters. `SESSION_HOURS` (default 8) sets the session length.

## Access control

All of it is in `app/services/access.py`, deliberately one file so it can be read in one
sitting. The rules come from `docs/schema.md` and `docs/threat-model.md`:

- **coach** sees and edits players in their own organization. A coach with no organization
  sees nobody, because failing closed surfaces a broken account instead of leaking a squad.
- **scout** reads across the population but **cannot see a minor without a current
  `scouting_visibility` consent**. Consent is signed at sign-up (see below), so in normal
  operation every minor is visible. If a guardian withdraws it, that minor comes back from
  search marked `withheld` with the name and date of birth stripped, and the screen renders a
  locked card.
- **federation** and **admin** read broadly. Only admins edit.
- **player** sees only their own record, and does not see model flags about themselves.

Two behaviours worth knowing before changing anything here:

A player the caller may not see returns **404, not 403**. A distinguishable status code tells
an unauthorised caller that the player exists, which for a child without scouting consent is
exactly the disclosure the rule exists to prevent.

**Consent is signed at sign-up.** Joining the platform means signing one consent form covering
storage, analytics and scouting visibility: a named guardian signs for a minor, the player
for an adult. `POST /players` refuses a player without it (422) and saves the three consent
rows and a `consent.grant` audit entry in the same transaction. The synthetic dataset follows
the same model, so no seeded player is withheld. The consent check still runs on every scout
request, because withdrawal is the safeguard offered to parents.

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
