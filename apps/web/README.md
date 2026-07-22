# NorthStar web

Next.js 14 (App Router) frontend in TypeScript, styled with Tailwind. Responsive and
mobile-first, since coaches log players from their phones. Charts will use Recharts.

Right now this is a scaffold: a landing page that shows "NorthStar" and a connectivity
widget that calls the API `/health/db` endpoint to prove the local stack is wired together.

## Layout

```
app/
  layout.tsx        root layout and metadata
  page.tsx          landing page
  health-check.tsx  client widget that pings the API
  globals.css       Tailwind entry + base styles
tailwind.config.ts  Tailwind config
next.config.mjs     Next.js config
```

## Run with Docker (recommended)

From the repo root:

```bash
docker compose -f docker/docker-compose.yml up --build web
```

Open http://localhost:3000. A green "API and database reachable" line means the whole local
stack (web, API, Postgres) is talking.

## Run without Docker

Needs Node 20+. From `apps/web`:

```bash
npm install
npm run dev
```

The app expects the API at `http://localhost:8000`. Override with `NEXT_PUBLIC_API_URL` if
your API runs elsewhere.

## Notes

- This package is part of the repo-root npm workspaces. You can also install from the root
  with a single `npm install`.
- shadcn/ui components and Recharts get added when UI work begins. TODO.
