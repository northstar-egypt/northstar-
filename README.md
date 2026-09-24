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
ml/             Detectors, the scoring harness, and the flag writer
tests/e2e/      Browser tests that run the demo flow end to end, in Firefox
docs/           architecture, schema, threat model, decisions log
docker/         docker-compose, Dockerfiles, and the seed container
```

## Run it locally

You need **Docker** and **Docker Compose**. That is the only hard requirement. Node 20 and
Python 3.11 are needed only if you want to run a piece outside Docker.

```bash
git clone <this-repo>
cd NorthStar
cp .env.example .env
docker compose -f docker/docker-compose.yml up --build
```

The first boot takes a few minutes. It brings up Postgres, the API and the web app, and runs
a one-shot `seed` container that migrates the database, loads the synthetic dataset, and runs
the detectors so the integrity board has cases in it. Wait for this line before opening the
browser:

```
northstar-seed  | [seed] done. the stack has data.
```

Then open **http://localhost:3000** and sign in. There is no password: the security
workstream has not chosen an auth approach yet, so the login screen offers one real account
per role and the API identifies callers by a header that only works in development.

| Sign in as | Lands on | Worth looking at |
| ---------- | -------- | ---------------- |
| Coach      | Dashboard | the squad scoped to that coach's academy, with growth sparklines and how long since each player was measured |
| Coach      | a player  | growth curve against the population band, percentiles, consent and provenance |
| Scout      | Search    | try `under 16 striker`. The chips show how the query was read, and minors without scouting consent appear as locked cards |
| Federation | Oversight | national coverage, staleness, flag counts |
| Federation | Integrity | the review queue. Open a duplicate case: the field-by-field diff is the decision |

The amber dropdown in the top right switches role. It is not a display toggle: it changes
which account the API answers as, so the data changes with it.

| Service   | URL                              | Notes                                   |
| --------- | -------------------------------- | --------------------------------------- |
| Web       | http://localhost:3000            | the application                         |
| API docs  | http://localhost:8000/docs       | every endpoint, interactive             |
| API       | http://localhost:8000/health     | liveness                                |
| API (db)  | http://localhost:8000/health/db  | confirms the database connection        |
| Postgres  | localhost:5432                   | user/pass/db from `.env`                |
| Ollama    | http://localhost:11434           | optional, enable with the `llm` profile |

Ollama is heavy, so it is behind a compose profile and off by default:

```bash
docker compose -f docker/docker-compose.yml --profile llm up
```

### About the data

**Everything you see is synthetic.** It is generated from a committed seed, so the same
dataset appears on every machine and two people comparing model scores are comparing the same
thing. No real player data is in this repository, and none ever will be: see the data hygiene
rules in [CLAUDE.md](CLAUDE.md).

Re-running `up` will not overwrite a database that already has players in it, so restarting
the stack does not throw away decisions made on the integrity board. To start over from
scratch, take the volume with it:

```bash
docker compose -f docker/docker-compose.yml down -v
```

### What is not built

One thing on the screens does not work: **adding a player**. `POST /players` and
`POST /players/{id}/measurements` are not implemented, so the add-player form reports that
nothing was saved rather than pretending. Everything else reads from the real API.

### Running pieces outside Docker

```bash
# the detector evaluation: precision, recall and F1 against the planted ground truth
pip install -r data/pipelines/requirements.txt -r ml/requirements.txt
python -m data.pipelines.synthetic.generate
python -m ml.run_eval

# the API test suite, including the access-control tests (needs the db container up)
pip install -r apps/api/requirements.txt -r apps/api/requirements-dev.txt
pytest apps/api/tests

# the end-to-end browser tests, in Firefox
python -m playwright install firefox
pytest tests/e2e
```

On Windows, set `PYTHONIOENCODING=utf-8` first: the generated player names are Arabic.

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
