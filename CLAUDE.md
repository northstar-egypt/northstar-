# CLAUDE.md

Context for AI coding sessions (and any human) working in this repo. Read this first.

## What NorthStar is

NorthStar is a national talent database and intelligence platform for Egyptian sports.
It is a computer science graduation project. The goal is centralized data infrastructure
for athletic talent in Egypt, starting with football and table tennis. Today talent gets
discovered by chance, not by system. NorthStar is the infrastructure that fixes that.

The platform ingests player data, tracks it over time, runs analytics and ML on it
(forecasting, similarity, late-bloomer and fraud detection), and exposes it through a
role-based web application for coaches, scouts, federations, and players.

## Scope (locked)

### Football module (deep implementation), three tiers
- **Pro tier**: Egyptian Premier League players. Data via the licensed FootyStats API.
  Analytics: trend analysis, sustainability (xG vs actual), player similarity, breakout flags.
- **Youth tier**: academy players, logged manually by coaches, seeded with realistic
  synthetic data. Analytics: growth-curve tracking, maturity-aware comparison,
  late-bloomer detection.
- **Diaspora tier**: Egypt-eligible players in foreign leagues, tracked from public
  European data (Transfermarkt-style sources).

### Table tennis module (generalization proof)
- ITTF/WTT results data (scraped) plus self-submitted player profiles for players seeking
  club opportunities abroad. Same engine, sport-specific fields.

## The core architecture principle: shared core + pluggable sport modules

This is the single most important design idea in the project. Do not violate it.

- Player identity, biometrics, time-series measurements, and organizational structure are
  **common across all sports** and live in normal relational columns.
- Sport-specific performance metrics live in a **flexible JSON field** (`PerformanceEntry.metrics`)
  validated by a **per-sport JSON schema** that lives in `packages/shared`.
- Adding a new sport should be a **config change** (a new validation schema + some metric
  definitions), not a database schema rewrite.

When you are tempted to add a football-specific or table-tennis-specific column to a core
table, stop. It almost certainly belongs in the JSON metrics field with a schema entry.

## Tech stack

- **Backend / data**: Python 3.11+, FastAPI, PostgreSQL, SQLAlchemy 2.0 + Alembic (migrations),
  pandas, NumPy, scikit-learn, statsmodels, sentence-transformers, Playwright (scraping),
  Faker (synthetic data), Ollama (local LLM).
- **Frontend**: Next.js 14+ (App Router), TypeScript, Tailwind, shadcn/ui, Recharts.
- **Infra**: Docker + docker-compose for local dev (Postgres + API + web + Ollama).
  GitHub Actions for CI later.
- Everything is free / self-hosted. The only paid service is the FootyStats API subscription.

## Repo layout

```
/apps
  /web          Next.js frontend (TypeScript, App Router, Tailwind)
  /api          Python FastAPI backend (SQLAlchemy + Alembic)
/packages
  /shared       Shared types and per-sport validation schemas (TS + Python, hand-written for now)
/data
  /pipelines    Ingestion scripts: footystats, ittf scraper, synthetic generator, bulk import
  /migrations   Postgres migration notes / SQL (Alembic migrations live under apps/api)
/ml             Model code and evaluation harnesses
/docs           architecture.md, schema.md, threat model, decisions log
/docker         docker-compose and Dockerfiles
```

## Workstreams (9-person team, four tracks)

1. **Data engineering**: unified Postgres schema, ingestion pipelines, validation and
   cleaning, synthetic data generator with planted ground-truth cases (late bloomers,
   fraud attempts, duplicates).
2. **Intelligence / ML**: forecasting (XGBoost or similar), per-position age curves,
   xG-vs-actual sustainability flags, similarity via embeddings, late-bloomer detection,
   anomaly detection, and an Ollama-hosted LLM assistant for grounded NL queries.
3. **Security**: JWT/session auth, role-based access control (coach / scout / federation /
   player), audit logging, minors' privacy safeguards, upload validation, fraud detection
   on self-submitted data, threat model docs.
4. **Application**: responsive Next.js web app, mobile-first for coach logging. Key screens:
   role-based login, coach dashboard, add/edit player, player profile (growth curves,
   forecasts with uncertainty, percentile bars, flags, AI summary), scout search,
   comparison view, federation oversight, integrity board.

## Evaluation targets (we are graded on these)

- **Detectors** (late-bloomer, fraud, duplicate): precision / recall / F1 against planted
  ground truth in synthetic data.
- **Trajectory forecasts**: walk-forward validation, MAE / RMSE against last-value and
  population-average baselines.
- **Access control**: every RBAC test must pass.
- **System**: end-to-end demo flow. Log a player, see profile, search, find them, flag
  surfaces, federation reviews.

## Conventions

- **Docs**: write for a teammate who has never seen the project. No em dashes anywhere in
  docs; use commas or periods.
- **Commits**: Conventional Commits style (`feat(api): ...`, `docs: ...`, `chore: ...`).
- **Don't overbuild**: this repo is a foundation. If in doubt, leave a `TODO` and move on.
  Prefer boring, standard choices so all nine teammates can contribute.
- **Ask before significant or irreversible choices** (a new core dependency, a schema
  change, an auth library). Two reasonable options means pause and ask.
- **Secrets**: never commit real credentials. `.env.example` is committed; real `.env` is
  gitignored.
- **Minors**: much of the youth data is about children. Privacy safeguards and consent
  tracking are first-class, not afterthoughts. See `docs/schema.md` (Consent, AuditLog).

## Running locally

```bash
cp .env.example .env
docker compose -f docker/docker-compose.yml up --build
```

- Web: http://localhost:3000
- API: http://localhost:8000 (health at `/health`, DB health at `/health/db`)
- Postgres: localhost:5432
- Ollama: http://localhost:11434 (placeholder, off by default profile)

See `README.md` for the full setup and `docs/architecture.md` for how the pieces fit.
