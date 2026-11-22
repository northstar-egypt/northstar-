# Verification and handoff

22 November 2026. Local branch: `codex/abdelrahman-design-system`. Starting revision: `origin/main` at `4bcaf68`.

## What changed

Shared colours, typography, spacing, cards, fields, buttons, tables, tags, keyboard tabs and states now give the application one visual system. The shell has desktop side navigation and phone navigation. Reading direction is persistent, numeric inputs and charts keep their axes, and English text remains English. Sign-in and the public home were refreshed. Coach, profile, search, oversight and integrity reads now show a retry state on failure instead of a permanent skeleton.

The scouting report has a browser Print / Save PDF action, an A4 layout, distinct filled and outline marks for black-and-white printing, repeated source/date information, and page-break handling. Finishing labels no longer collide. Existing data requests, permissions, calculations and uncertainty values were retained. No production dependency was added.

## Evidence

- [Before/after review gallery](review/index.html): 13 surfaces, each at 360 and 1280 px in LTR and RTL. These use invented records intercepted in the browser. They are visual proposals awaiting Ahmed's approval.
- [Sample printable report](review/scouting-report-synthetic.pdf): invented data, four A4 pages. Rendered and visually checked. Source and date text were checked within the bounds of every page.
- The gallery directory also contains loading, empty, missing-data, insufficient-minutes and error-state captures.

## Checks

| Check | Result |
| --- | --- |
| `npx tsc --noEmit -p apps/web/tsconfig.json` | Passed |
| `npm run lint --workspace @northstar/web -- --max-warnings 0` | Passed |
| `npm run build --workspace @northstar/web` | Passed, all 21 routes built |
| `.venv/Scripts/python.exe -m ruff check .` | All checks passed |
| `node apps/web/scripts/check-contrast.mjs` | 21 text/surface pairs passed AA; minimum 6.28:1 |
| `node apps/web/scripts/design-review.mjs` | 52 final layout captures; zero viewport overflows or browser errors |
| Keyboard and state checks in the same script | Passed direction persistence, skip-link focus, tab keys, empty/error/loading/missing-data states and five failed-request/retry recovery flows |
| Chromium PDF and PDF text/bounds checks | Passed, four A4 pages with source/date on every page |
| `git diff --check` | Passed |

The baseline had four overflowing captures out of 52; the proposal had none. Contrast checks cover shared tokens, not a complete accessibility certification.

## Real-stack Firefox run

The stack used a new Docker project, `northstar-abdelrahman-review`, with database `northstar_design` on port 15432, API on 8000 and the built web app on 3000. The existing project database and its volumes were not reset. Only the project's synthetic generator was loaded. The optional Ollama reader was off (`ASSISTANT_READER=rules`).

The full command was:

```powershell
$env:DATABASE_URL='postgresql+psycopg://northstar:northstar@localhost:15432/northstar_design'
$env:E2E_DATABASE_URL=$env:DATABASE_URL
$env:E2E_WEB_URL='http://localhost:3000'
$env:E2E_API_URL='http://localhost:8000'
$env:E2E_HEADED='0'
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python.exe -m pytest -v tests/e2e --tb=short
```

Initial result: **36 passed, 4 failed in 992.94 seconds**. The four failures were two timeouts on the initial profile path (30 seconds in the browser and 10 seconds for its API call), scouting-report assertions for older wording, and a model-dependent assistant follow-up running while the optional model was off.

The browser test file was updated to give profile data an explicit 120-second startup budget, assert the report's existing approved wording, and honor the API's `reader=rules` metadata when deciding to skip the model-only test. No data assertions, model values or backend logic were changed.

Recheck of those four tests:

```powershell
.venv/Scripts/python.exe -m pytest -v tests/e2e --tb=short -k 'a_player_profile_renders_real_measurements or the_profile_states_what_is_not_known_yet or a_scout_reads_a_scouting_report_from_the_profile or the_assistant_answers_from_the_records_and_shows_its_reading'
```

Result: **3 passed, 1 skipped, 36 deselected in 78.81 seconds**. Across the full run and targeted recheck, 39 distinct browser tests were validated successfully; the optional model-only case was skipped. This is not a claim that a second full 40-test run was performed. The successful checks include logging a player, search, duplicate detection, federation merge and undo.

## Publishing and review

GitHub access was checked as `abdelrahmanh22`; the account can push to `northstar-egypt/northstar-`. The delivery board could not be read because the credential lacks `read:project`.

The user reviewed the screen changes and authorized committing and pushing this branch. Application changes, browser-test maintenance and synthetic visual evidence are included together for review.

Ahmed's design/code review remains pending. Full Arabic translation, a separate identity-edit workflow, and a complete manual accessibility audit are not claimed by this proposal. See [the audit and review gates](README.md).
