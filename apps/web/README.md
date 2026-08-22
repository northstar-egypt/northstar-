# NorthStar web

Next.js 14 (App Router) frontend in TypeScript, styled with Tailwind. Responsive, and mobile
first on the screens a coach uses pitchside.

All eight screens from `docs/wireframes` are built and navigable. Read that first: the
wireframes carry the reasoning for why each screen is laid out the way it is, and this app is
the implementation of them.

## The important caveat

**Most of what you see is synthetic.** The API serves `/health` and `/health/db` and nothing
else, so every other screen reads from fixtures. Nothing here is a working product yet; it is a
reviewable prototype of the interface with the seams left visible on purpose.

Two things make that honest rather than misleading:

- Every unbuilt endpoint is a function in `lib/api.ts` carrying a TODO that names the route it
  should call and the tables behind it. Those TODOs are the application track's request to the
  data track, written where they cannot be lost.
- The banner in the app and the dotted underlines on model-derived numbers say so on screen.

Switching to the real API is a change in `lib/api.ts` and nowhere else. No screen imports
fixtures directly.

## Layout

```
app/
  layout.tsx            root layout, wraps everything in AuthProvider
  page.tsx              entry, redirects by role or to login
  login/                sign in, and the demo role picker
  (app)/                every signed in screen, shares nav and the role redirect
    dashboard/          coach dashboard
    players/new/        add a player, log a measurement
    players/[id]/       player profile
    search/             scout search
    compare/            comparison
    oversight/          federation oversight
    integrity/          integrity board
components/
  ui.tsx                buttons, cards, chips, tables, banners
  charts.tsx            sparkline, growth curve, percentile bar, bars, stacks
  nav.tsx               top navigation and the development role switcher
  api-status.tsx        connectivity indicator, the one real API call
lib/
  api.ts                every call to the outside world, and every TODO
  types.ts              shared core types plus proposed response shapes
  fixtures.ts           synthetic data, delete when the generator lands
  auth.tsx              session state, NOT authentication
  format.ts             small formatting helpers
```

## Two deliberate absences

**No component library.** CLAUDE.md names shadcn/ui, but installing it is a new core
dependency and the same file says to ask first. `components/ui.tsx` covers what these screens
need and is small enough to throw away if the team wants shadcn.

**No chart library.** Same reasoning for Recharts. The four charts in `components/charts.tsx`
are hand written SVG with no dependencies. If the team adopts Recharts, those components are
the spec for what to build.

Neither decision is defended to the death. They exist so that reviewing the screens does not
also mean approving two dependencies.

## Authentication

There is none, and `lib/auth.tsx` says so at the top. It holds a role in localStorage so the
role-dependent screens can be reviewed. It verifies no password and decides no permissions.

The rule the whole app follows: **role is a hint for what to render, never the enforcement
boundary.** If the API sends a field the current role should not see, hiding it in the browser
has not protected anything. Access control belongs in the API, and it is the security
workstream's next task.

The role switcher in the top bar is development only and disappears with real sign in.

## Run with Docker (recommended)

From the repo root:

```bash
docker compose -f docker/docker-compose.yml up --build
```

Open http://localhost:3000. You land on the login page. Pick a demo role.

## Run without Docker

Needs Node 20+. From `apps/web`:

```bash
npm install
npm run dev
```

The app expects the API at `http://localhost:8000`. Override with `NEXT_PUBLIC_API_URL`. The
screens work without the API running; only the connectivity indicator in the footer will show
red.

## Checks

```bash
npx tsc --noEmit
npm run build
```

Both pass. There are no tests yet, which is a real gap rather than an oversight: the screens
worth testing are the ones with logic in them, which today means the plausibility warning on
measurement entry and the indistinguishable-values rule on comparison.

## Notes

- This package is part of the repo-root npm workspaces.
- `apps/web/lib/` needs an explicit exception in the root `.gitignore`, because the Python
  section ignores any directory called `lib`. Do not remove it.
