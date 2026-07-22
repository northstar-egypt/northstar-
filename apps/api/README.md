# NorthStar API

FastAPI backend. Serves the web app, owns all data access, enforces access control, and
orchestrates the ML and LLM layers. SQLAlchemy 2.0 for models, Alembic for migrations.

## Layout

```
app/
  main.py        FastAPI app, CORS, router mounting
  config.py      env-driven settings (pydantic-settings)
  db.py          engine, session factory, declarative Base, get_db dependency
  models/        ORM models for the shared core schema (to be built from docs/schema.md)
  routers/       API routers (health today; features later)
alembic/         migration environment and versions
alembic.ini      Alembic config (DB URL comes from the environment, not this file)
requirements.txt pinned dependencies
Dockerfile       Python 3.11 slim image
```

## Run with Docker (recommended)

From the repo root:

```bash
docker compose -f docker/docker-compose.yml up --build api
```

The API comes up on http://localhost:8000. Endpoints:

- `GET /` small info payload
- `GET /health` liveness
- `GET /health/db` confirms the database is reachable
- `GET /docs` interactive API docs

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
