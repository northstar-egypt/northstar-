# NorthStar

A national talent database and intelligence platform for Egyptian sports, starting with
football and table tennis.

Egypt has around 120 million people and real athletic talent, but no centralized data
infrastructure for it. Youth academies keep scattered records, professional player data is
owned by foreign providers, and dual-national players eligible for Egypt are not tracked at
all. Talent gets discovered by chance, not by system. NorthStar is the infrastructure that
fixes that.

This is a computer science graduation project built by a team of nine.

## What it does

NorthStar ingests player data from several sources, tracks each player over time, runs
analytics and machine learning on that history, and presents it through a role-based web
app for coaches, scouts, federations, and players.

- **Track talent over time.** Growth curves, trend charts, and forecasts with uncertainty
  bands, not just a single snapshot.
- **Find hidden talent.** Late-bloomer detection, maturity-aware comparison, and semantic
  search so a scout can describe what they want in plain language.
- **Keep the data honest.** Fraud and duplicate detection on self-submitted data, audit
  logging, and privacy safeguards for minors.
- **Generalize across sports.** A shared core with pluggable sport modules, proven by
  running both football and table tennis on the same engine.

## Scope

### Football (deep implementation), three tiers
- **Pro**: Egyptian Premier League players via the licensed FootyStats API. Trend analysis,
  sustainability (xG vs actual), similarity, breakout flags.
- **Youth**: academy players logged by coaches, seeded with realistic synthetic data.
  Growth-curve tracking, maturity-aware comparison, late-bloomer detection.
- **Diaspora**: Egypt-eligible players in foreign leagues, from public European data.

### Table tennis (generalization proof)
- ITTF/WTT results (scraped) plus self-submitted profiles for players seeking clubs abroad.
  Same engine, sport-specific fields.

## Architecture in one paragraph

A **shared core** holds everything common across sports: player identity, biometrics,
time-series measurements, and organizational structure, all in normal relational tables.
**Sport-specific performance metrics** live in a flexible JSON field validated by a
per-sport schema. Adding a new sport is a config change, not a database rewrite. A Python
FastAPI backend serves a Next.js frontend, both backed by PostgreSQL, with ingestion
pipelines feeding the database and an ML layer plus a local Ollama LLM producing the
intelligence. See [docs/architecture.md](docs/architecture.md) for the full picture and
[docs/schema.md](docs/schema.md) for the data contract.

## Repo layout

```
apps/
  web/          Next.js frontend (TypeScript, App Router, Tailwind, Recharts)
  api/          FastAPI backend (SQLAlchemy 2.0 + Alembic)
packages/
  shared/       Shared types and per-sport validation schemas (TS + Python)
data/
  pipelines/    Ingestion: footystats, ittf scraper, synthetic generator, bulk import
  migrations/   Migration notes (Alembic migrations live under apps/api)
ml/             Model code and evaluation harnesses
docs/           architecture, schema, threat model, decisions log
docker/         docker-compose and Dockerfiles
```

## Run it locally

You need **Docker** and **Docker Compose**. That is the only hard requirement to boot the
stack. Node 20 and Python 3.11 are only needed if you want to run an app outside Docker.

```bash
git clone <this-repo>
cd NorthStar
cp .env.example .env
docker compose -f docker/docker-compose.yml up --build
```

Then open:

| Service   | URL                              | Notes                                  |
| --------- | -------------------------------- | -------------------------------------- |
| Web       | http://localhost:3000            | Landing page proves API connectivity   |
| API       | http://localhost:8000/health     | Health check                           |
| API (db)  | http://localhost:8000/health/db  | Confirms the database connection       |
| API docs  | http://localhost:8000/docs       | FastAPI interactive docs               |
| Postgres  | localhost:5432                   | User/pass/db from `.env`               |
| Ollama    | http://localhost:11434           | Optional, enable with the `llm` profile |

Ollama is heavy, so it is behind a compose profile and off by default. Start it with:

```bash
docker compose -f docker/docker-compose.yml --profile llm up
```

The apps are near-empty scaffolds right now. A green landing page and healthy `/health/db`
mean your environment is set up correctly and you are ready to build.

## The four workstreams

NorthStar is built across four tracks. Pick the one that matches your role.

1. **Data engineering.** Unified Postgres schema, ingestion pipelines (FootyStats API,
   ITTF scraper via Playwright, coach logging, self-submission, bulk import), a validation
   and cleaning layer, and a synthetic data generator with planted ground-truth cases
   (late bloomers, fraud attempts, duplicates).
2. **Intelligence / ML.** Performance forecasting, per-position age curves, xG-vs-actual
   sustainability flags, player similarity via sentence-transformer embeddings, late-bloomer
   detection, anomaly detection, and an Ollama-hosted assistant for grounded natural-language
   queries.
3. **Security.** JWT/session auth, role-based access control (coach / scout / federation /
   player), audit logging, minors' privacy safeguards, upload validation, fraud detection on
   self-submitted data, and threat model documentation.
4. **Application.** Responsive Next.js web app, mobile-first for coach logging. Role-based
   login, coach dashboard, add/edit player, the player profile page (the crown jewel),
   scout search, comparison view, federation oversight, and an integrity board.

## How to contribute

1. Read [CLAUDE.md](CLAUDE.md) and [docs/architecture.md](docs/architecture.md) so you share
   the team's mental model, especially the shared-core + sport-modules principle.
2. Branch off `main`. Use a short descriptive branch name, for example
   `data/synthetic-generator` or `web/player-profile`.
3. Write [Conventional Commits](https://www.conventionalcommits.org/): `feat(api): ...`,
   `fix(web): ...`, `docs: ...`, `chore: ...`.
4. Keep docs readable by someone new to the project. No em dashes in docs.
5. Never commit secrets. `.env.example` is the template; your real `.env` is gitignored.
6. Open a pull request into `main` and ask for a review from the relevant workstream.

## Status

Foundation stage. The repo has the monorepo layout, a working local stack, the data
contract draft, and near-empty app scaffolds. Feature work starts next. Anything unfinished
is marked with a `TODO` in code or a checkbox in the docs.
