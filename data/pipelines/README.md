# Ingestion pipelines

Owner: data-engineering workstream. Scripts that pull data from each source, normalize it
into the shared core shape, validate it, and load it into PostgreSQL.

Every source has an adapter. All adapters feed one validation and cleaning layer before the
database, so the DB only ever holds validated data. Sport-specific `metrics` are validated
against the per-sport JSON schemas in `packages/shared/schemas`.

## Planned pipelines

- `footystats/` Pull Egyptian Premier League (pro tier) data from the FootyStats API.
  Needs `FOOTYSTATS_API_KEY`. TODO.
- `ittf/` Scrape ITTF/WTT results for table tennis using Playwright. TODO.
- `diaspora/` Collect Egypt-eligible players from public European sources. TODO.
- `synthetic/` Generate realistic synthetic data with **planted ground-truth cases**
  (late bloomers, fraud attempts, duplicates) so detectors and forecasts have a labeled set
  to be measured against. This is the first one to build; it unblocks the ML workstream
  before any real data or API subscription exists. TODO.
- `bulk_import/` Validated CSV/spreadsheet import for academies with existing records. TODO.

## Conventions

- Normalize to the shared core (see `docs/schema.md`) before writing.
- Never write unvalidated data. Record source and validation outcome on every row.
- Keep credentials in the environment, never in code. See `.env.example`.
- Heavy Python deps (pandas, Playwright, Faker) belong in a requirements file here, kept
  separate from the API image so the API stays lean. TODO: add `requirements.txt`.
