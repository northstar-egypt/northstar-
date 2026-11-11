# Ingestion pipelines

Owner: data-engineering workstream. Scripts that pull data from each source, normalize it
into the shared core shape, validate it, and load it into PostgreSQL.

Every source has an adapter. All adapters feed one validation and cleaning layer before the
database, so the DB only ever holds validated data. Sport-specific `metrics` are validated
against the sport modules in `packages/shared/sports`, through `app.sports.validate`. The
synthetic generator already does: every row it writes must pass, and the only rows in a
dataset that fail are the planted fraud rows.

## Pipelines

Built:

- `synthetic/` Generates realistic synthetic data with **planted ground-truth cases**
  (late bloomers, fraud attempts, duplicates, table tennis result tampering) so detectors and
  forecasts have a labelled set to be measured against. It also generates the pro tier's
  synthetic Egyptian league in FootyStats' shape. See `synthetic/README.md`.
- `geo/` Builds the governorate map of Egypt the federation home draws.

Built in the API instead of here, because they run from a screen in the app:

- Players from a spreadsheet: `apps/api/app/services/imports.py` (`POST /players/import`).
- Table tennis results from a spreadsheet, in place of a scraper: see `docs/results-import.md`
  for why there is no ITTF/WTT scraper.

Not built yet:

- `footystats/` Pull Egyptian Premier League data from the FootyStats API into the tables the
  synthetic league already fills. Needs `FOOTYSTATS_API_KEY`, so it waits on the API subscription.
- Diaspora: the source is not decided (`docs/project-status.md`).

## Conventions

- Normalize to the shared core (see `docs/schema.md`) before writing.
- Never write unvalidated data. Record source and validation outcome on every row.
- Keep credentials in the environment, never in code. See `.env.example`.
- Heavy Python deps (pandas, Faker, and Playwright for the browser tests) live in `requirements.txt` here, kept
  separate from the API image so the API stays lean.
