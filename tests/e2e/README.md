# End-to-end tests

The graded system target is a demo flow, not a screenshot: *log a player, see the profile,
search, find them, a flag surfaces, the federation reviews it.* This directory is that flow
written down so it can be re-run, rather than described in a slide and performed by hand.

It drives a real browser against a real API against a real PostgreSQL. Nothing here is mocked,
which is the point: `apps/api/tests` proves the API returns the right JSON and
`npm run build` proves the frontend compiles, and neither of them notices a screen that
fetches correctly and then renders nothing.

## Firefox

Playwright is already pinned in `data/pipelines/requirements.txt` for the ITTF scraper, and it
drives Firefox natively. **These tests use Firefox because that is the browser the team
actually uses.** A pass in a browser nobody opens is worth less than a pass in the one
everybody does.

Playwright downloads its own Firefox into its cache. It does not touch the Firefox installed
on the machine and does not use its profile.

## Running them

Four things have to be up. From the repository root:

```bash
# 1. database, migrated, with the synthetic dataset in it
docker compose -f docker/docker-compose.yml up -d db
cd apps/api && alembic upgrade head && cd ../..
python -m data.pipelines.synthetic.generate --database-url $DATABASE_URL --truncate

# 2. flags, so the integrity board has something to show
python -m ml.write_flags

# 3. the API
cd apps/api && uvicorn app.main:app --port 8000

# 4. the web app, in another terminal
npm run build --workspace @northstar/web
npx next start -p 3000 --dir apps/web
```

Then:

```bash
python -m playwright install firefox     # once
pytest tests/e2e
```

The suite skips, with a message saying what is missing, when the web app or the API is not
answering. A red suite should mean a broken application, not a forgotten terminal.

`--headed` is not a pytest flag here; set `E2E_HEADED=1` to watch it run, which is the
fastest way to understand a failure.

## What these tests are careful about

**Rendered text, not source text.** An early version of this suite asserted `"Squad size"`
and failed on a page that was working perfectly, because the stat labels are uppercased in
CSS and the browser reports `SQUAD SIZE`. Every text assertion here is case-insensitive for
that reason. The lesson generalises: assert on what the user sees, and remember that CSS
changes what that is.

**Real data, not any data.** Asserting that a table has rows would pass against a fixture. The
assertions check values that can only have come from the database, such as the organization
name on the caller's account and counts that match what the API reports.

**The access-control boundary.** A scout's search is expected to contain withheld cards, and
a withheld card is expected to carry no name. That is the rule most worth catching a
regression in, because breaking it leaks a child's identity and nothing else in the suite
would notice.
