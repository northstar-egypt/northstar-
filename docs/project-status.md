# Project status and handoff

Last updated: 2026-11-11, with `main` at PR #100. This is the "where we are, what to do next"
page for anyone joining or picking up the work, written for a teammate who has not seen the
repo yet. The live task board is the NorthStar Delivery project (link in `CLAUDE.md`). The
model results are in `ml/README.md`; this page does not repeat them, because they move and
that file is the one kept current.

## Where the project is, in one paragraph

The product is built end to end on synthetic data. A coach can log a player, a scout can find
them, the models raise flags, and the federation reviews them, all through the real API behind
a real sign-in, and the Firefox end-to-end tests drive that flow. What is not yet connected is
any live outside data source: the professional league, the diaspora tier and table tennis
results all run on generated data or on spreadsheets a person imports. The FootyStats
connection is ready to build once the API subscription is taken; until then the pro tier runs
on the synthetic league (see "What to do next").

## What is built

**Platform**

- Docker Compose stack: Postgres 16, the FastAPI API, the Next.js 15 web app, a one-shot seed
  container, and Ollama behind the `llm` profile (with a GPU override file).
- Sign-in with our own JWT in an HttpOnly cookie, argon2id passwords, role-based access
  control for coach, scout, federation, player and admin, audit logging, and consent signed at
  sign-up with withdrawal. Design and known gaps: `docs/threat-model.md`.
- Shared core plus sport modules: football and table tennis metrics are JSON validated by the
  modules in `packages/shared/sports`, enforced by the generator, the API and the detectors.

**Data**

- Synthetic generator (`data/pipelines/synthetic`) with planted ground truth: late bloomers,
  age fraud, implausible self-reported performance, table tennis result tampering and
  duplicates. It also generates a synthetic Egyptian league in FootyStats' shape for the pro
  tier, and tagged match events.
- Imports: players from a spreadsheet with a preview first (#61), and table tennis results
  from a spreadsheet in place of a scraper (#74, reasons in `docs/results-import.md`).
- Coaches tag match events from video: shots on a pitch, points on a table (#70, #73, #87).

**Intelligence** (results and limits in `ml/README.md`)

- Detectors: late bloomer, fraud (three rules), duplicate, scored against the planted answer
  key, with thresholds tuned on seeds 101, 202 and 303 only.
- The late-bloomer backtest: would the system have flagged a late bloomer at the moment a
  size-based cut released them?
- Height forecasts with an 80% band (cohort velocity, XGBoost challenger), table tennis
  opponent-adjusted point rating, player similarity, percentile radars, relative age audit.
- Pro tier: breakouts, finishing against expected goals, season trends, team gap analysis for
  a club and for the national team, and a scouting report.
- The assistant (Ask): questions in plain words, answered from our own queries and shown as
  cards and bars; a local model only reads the question and phrases the answer. Profile
  summaries are checked number by number before they are shown.

**Application**

- A home screen per role (coach, scout, player, federation), the "ones we'd have let go" story
  screen and a landing page.
- Player profile, add player, log a measurement, import, scout search, compare, the scatter
  explorer and position leaders, team gaps, match tagging, federation oversight with a map of
  Egypt, the integrity board (confirming a duplicate merges the records, and a merge can be
  undone).
- `docs/demo.md` is the graded demo as a ten-minute script, and
  `python tests/e2e/demo_check.py` checks the stack is ready for it.

## Where each data source stands

| Source in the scope | Today | What it would take |
| --- | --- | --- |
| Youth academies | Synthetic, plus coach entry and spreadsheet import in the app | Nothing to build. Real academy data is not obtainable, so the youth tier stays synthetic by design |
| Pro tier (Egyptian Premier League) | A synthetic league in FootyStats' shape (#88) | A FootyStats client that fills the same tables. Waiting on the API subscription; the real field names are checked first |
| Diaspora | A tier value on synthetic players abroad | Not decided: a manual entry form with a source link, FootyStats leagues abroad, or future work. Transfermarkt's terms forbid scraping |
| Table tennis results | Spreadsheet import | ITTF and WTT block automated access (`docs/results-import.md`), so import stays the route |
| Player self-submission | Only in the synthetic data: rows marked `self_submitted`, which the fraud rules check | A screen where a player adds their own results, for table tennis players seeking clubs abroad |

No real player data is in this repository, and none ever will be (`CLAUDE.md`).

## What to do next, in order

1. **A demo that cannot fail on the day.** A recorded video of the full flow, Ask working
   without the GPU, and a database snapshot that restores in one command.
2. **Labelled decisions back into the detectors.** Every decision on the integrity board is a
   labelled example with a reason. Measure whether using them improves late-bloomer and
   age-fraud precision, and publish the result either way.
3. **FootyStats adapter, once the subscription is taken.** Waiting on the API key: the field
   names cannot be checked without it, and an adapter written against guessed fields would be
   rewritten. Then fill the pro-tier tables from the API instead of the generator. Key in
   `.env` only, responses cached in a gitignored folder, a test on the field names that uses no
   real data. Then breakouts, finishing and team gaps run on the real league.
4. **Diaspora decision** (see the table above).
5. Smaller pieces a teammate can pick up alone: split the player profile page
   (`apps/web/app/(app)/players/[id]/page.tsx`) into one component per card, add unit tests
   for `components/charts.tsx`, and finish or close the security plan draft (PR #54).

## Known gaps

Missing features that a reviewer might take for bugs are listed in the README under "What is
not built" (editing a player, offline saving, maturity, a national export, Compare on a phone,
password reset, self-submission by players). Model limits are under "Known limits" in `ml/README.md`.

## How to run it

See the README, "Run it locally". In short:

```bash
cp .env.example .env
docker compose -f docker/docker-compose.yml up --build
```

Wait for `[seed] done. the stack has data.`, then open http://localhost:3000. Every synthetic
account's password is `northstar-demo`.

## Who owns what

Four teams in the `northstar-egypt` org, one per workstream, all with write access to the
repo. Team membership is what gives you push access, so joining a team is the first step for
a new contributor.

| Team | Area of responsibility |
| --- | --- |
| `@northstar-egypt/data` | `data/`, `apps/api/`, the models and migrations, docs, docker |
| `@northstar-egypt/ml` | `ml/`, and `packages/shared` alongside the others |
| `@northstar-egypt/security` | the threat model, and the models and migrations alongside data |
| `@northstar-egypt/app` | `apps/web/` |

These are areas of responsibility, not merge rights. Review approval is separate: see below.

## How a change gets into main

`main` is protected. Nobody pushes to it directly.

1. Branch off `main`, do the work, push the branch.
2. Open a pull request. Say what changed, why, and how you verified it.
3. The CI checks `api`, `generator`, `ml` and `web` must pass; they are required. `lint` runs
   too and should be green.
4. Get an approving review from **@BModz**, the code owner of every path
   (`.github/CODEOWNERS`). Approvals are dismissed when new commits are pushed.
5. Resolve every review conversation, then squash merge. The branch is deleted automatically.

Request a workstream team by hand when you want their eyes on something, for example
`@northstar-egypt/security` on anything touching `User`, `Consent`, `AuditLog` or auth.

## Working agreement

- One branch per task, named `feat/...`, `fix/...`, `chore/...` or `docs/...`.
- Conventional Commits: `feat(api): ...`, `docs: ...`, `chore: ...`.
- If you touch the generator, `ml/detectors` or `ml/evaluation`, re-run the evaluations and
  put the before and after in the pull request (`CLAUDE.md`, "The quality bar").
- Move your task on the NorthStar Delivery board when you start it and when you finish it.
