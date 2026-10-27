# 0007. Details on tagged events, and the rates read from them

Status: accepted 2026-10-27.
Date: 2026-10-27

## Context

Coaches tag shots, passes and tackles from match video (decision 0005): where on the pitch,
and how it ended. That gives a shot map, not finishing. The questions a coach asks about
finishing need more than the outcome: where in the goal the ball went, how it was struck,
whether it was a one-on-one with the keeper, and how far away the keeper was. Published
analyses of professional one-on-ones (low through the middle and far post beating high
corners, chips no better than anything else) are built from exactly those fields.

FootyStats has no shot locations or event data, so none of this can come from the pro feed.
It can come only from the coaches' own tags, which is where it matters most: teaching
children to finish.

## Decision

1. **A `details` JSON column on `match_event`** (Alembic migration 0007, approved as a schema
   change), `{detail: value}`, nullable. Not columns, by the shared-core rule: which details
   exist is the sport module's.
2. **Details are declared in the sport module**, under each event type
   (`events.types.<type>.details`): a label, ordered values, optionally the outcomes they
   apply to (where in the goal is recorded for goals and saves, not misses), and optionally a
   grid (the goal mouth, 2 by 3, seen from the shooter). They are checked when a module loads
   and when a tag is saved or changed. Football's shot has `placement`, `technique`,
   `situation` and `keeper_distance`; table tennis's points have `stroke`.
3. **Details are optional and added after the outcome.** The tagging screen saves a tag the
   moment its outcome is picked, as before; a panel then offers the details that apply, each
   saved as it is picked (`PUT /events/{id}/details`, same rights as removing the tag,
   audited).
4. **Analyses are declared in the module too** (`events.analyses`): which event types are the
   attempts, what counts as a success, a verb for it, and the attempts a player needs before
   their own rate is shown. Football's `finishing` is shots that became goals (10 attempts);
   table tennis's `points` is points won (20). `GET /analysis/{sport}/{key}` returns the
   group's rate, the rate for each value of each detail, the best players, and a player's own
   rate and percentile. The screen is **Explore, Finishing**, and a card on the profile.
5. **The platform's rules hold.** Only players with analytics consent are counted. A player
   is named only to a caller who may open them; the others are counted but not identified.
   No rate is shown from fewer than 10 attempts; the counts are. The group is named.
6. **Generated tags are said to be generated.** Tags made by the synthetic data generator
   carry no tagger, coaches' own always do, so the analysis counts them and says so: "437 of
   these 439 tags were made by the synthetic data generator; the rates mix the two." The
   generator draws plausible details (data/pipelines/synthetic/tagged_events.py,
   `details_for`); the rates on the screen are how it was written, not findings.

## Consequences

- Adding a detail or an analysis to a sport is a config change; the tagging panel and the
  Finishing screen render whatever the module declares. Table tennis's points by stroke came
  with no table tennis code.
- The seed adds details to generated tags that have none, on every boot, drawn per tag from
  its id, so an existing database gets them and the same database always gets the same.
- Not built: a detail that applies only after another (keeper's distance only for a
  one-on-one) is offered on every shot; the coach leaves it empty when it does not apply.
- Not built: importing published professional event data (for example StatsBomb's open
  data) to run the same analysis on real matches. It is real data about real players under
  its own licence, so it is a separate decision, and it would never enter the repository.
