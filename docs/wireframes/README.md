# Wireframes

Static wireframes for the eight main screens of the NorthStar web app, drawn by the
application workstream before any of them is built.

Open [`index.html`](index.html) in a browser. No build step, no server, no dependencies.
Double click the file, or from the repo root open `docs/wireframes/index.html`.

## What these are for

The application track's next task is to wireframe the main screens, then build role based login
and the coach dashboard. Wireframing first is cheap, and the point is to have the arguments
about what belongs on a screen now, while changing a layout costs a few minutes instead of a
few days.

They are also a way to find gaps in the data contract by trying to draw against it. Two turned
up while drawing these, and both are listed at the bottom of this page.

## What these are not

Not a design. The palette is greyscale on purpose so that nobody mistakes a colour here for a
decision. Type, colour, spacing, and component choices come later, when the real screens are
built with Tailwind and shadcn/ui.

Not a commitment either. Anything drawn here that the team disagrees with is easier to change
now than at any later point, which is the entire reason for doing it this way.

## The screens

| File | Screen | Primary role |
| --- | --- | --- |
| `01-login.html` | Login | everyone |
| `02-coach-dashboard.html` | Coach dashboard | coach |
| `03-add-edit-player.html` | Add and edit player, log a measurement | coach |
| `04-player-profile.html` | Player profile | all four roles, different views |
| `05-scout-search.html` | Scout search | scout, federation |
| `06-comparison.html` | Comparison | scout, coach, federation |
| `07-federation-oversight.html` | Federation oversight | federation |
| `08-integrity-board.html` | Integrity board | federation, admin |

## Conventions

Solid boxes are real interface elements. Dashed hatched boxes are generated content: a chart,
a photo, a forecast, a model output. Numbered markers point to the annotation list under each
wireframe, which is where the reasoning is written down.

Every screen page ends with three sections: the data and endpoints it needs, the access rules
that apply to it, and the open questions the application track cannot answer alone.

## Two gaps these found

Worth reading even if you skip the wireframes themselves, because both affect tracks other than
the application one.

1. **There is no flag table in the schema.** The integrity board reviews fraud, duplicate, and
   anomaly flags, and `docs/schema.md` has no table that holds a raised flag with a status, a
   confidence, evidence, a reviewer, and a decision. The ML track writes those records, the
   application track reads them, and the security track audits them, so it belongs in the shared
   core. See `08-integrity-board.html` for the proposed field list.
2. **`Organization` has no region.** Federation oversight wants coverage by governorate, which
   is the clearest expression of the national mission in the whole product, and the schema
   stores an ISO country code and nothing finer. Adding a region field is a small change now and
   an awkward one once there is data. See `07-federation-oversight.html`.

Both are changes to the data contract, so per the repository conventions they go through a pull
request that flags the affected workstreams rather than being made quietly.

## Decisions these wireframes are waiting on

- **Auth and session handling** shapes the login screen. The security track's next task is the
  auth decision record, and the "stay signed in" control on `01-login.html` should not ship
  before that lands.
- **Consent gating behaviour.** When a scout matches a minor who has not consented to scouting
  visibility, do they see a locked card or nothing at all? Drawn as a locked card in
  `05-scout-search.html` so the team has something concrete to react to. Not decided.
- **Embedding model choice** gates the natural language half of scout search. The filters half
  can ship without it.
- **Maturity offset method** gates the comparison screen's second view, which is the most
  valuable thing on it.
