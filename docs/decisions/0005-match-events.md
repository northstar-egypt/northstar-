# 0005. Match events tagged from video: their own table, types from the sport module

Status: accepted 2026-10-23.
Date: 2026-10-23

## Context

Everything the platform knows about a match is a player's totals for it: 3 shots, 41 passes,
2 tackles (`PerformanceEntry.metrics`). Totals say how much, not where or how: a shot from the
six-yard box and one from 35 metres count the same. Scouting tools such as DataMB show shot
maps and event-level statistics, and those need one record per action.

There is no event data for Egyptian youth football, and none is coming from a provider. The
only realistic source is the coaches: a coach watching a recording of a match can tag each
shot, pass and tackle, with where on the pitch it happened. A person tagging video makes
mistakes, so the data is approximate. The aim is useful at roughly 55 to 60% of what a
professional event provider would get, labelled as what it is.

## Decision

1. **A new core table, `match_event`** (Alembic migration 0004), one row per tagged action:
   the player, the club, the match (date and the coach's own short label), the event type and
   its outcome, where on the pitch (0 to 100 on both axes, attacking to the right), the time in
   the coach's video, the source (`coach_tagged`) and who tagged it.
2. **Types and outcomes come from the sport module**, under `events` in
   `packages/shared/sports/<sport>.json`, and are checked when an event is saved. Football has
   shots (goal, saved, off target, blocked), passes (complete, incomplete, key pass, assist)
   and tackles (won, lost). Each outcome names the match totals it counts toward (`counts`),
   which the module loader checks are real totals of the match record. Adding an event type is
   a config change, as the shared-core rule requires (decision 0001).
3. **The video is never uploaded.** The coach opens it from their own device on the tagging
   screen and only the tags are saved, each with the video time so it can be found and checked
   again. No video storage, no upload limits, and no recordings of children on our servers.
4. **Rules.** Whoever may log for the player (their own club's coaches, admins) may tag and
   remove tags; both are written to the audit log. Whoever may open the player may read their
   events, as with the match records on the profile.
5. **Tags are set beside the logged totals.** The tagging screen adds each player's tags up
   into match totals and shows them next to what was logged for that date, highlighting where
   they differ. Tags do not overwrite logged totals.

## Alternatives considered

- **A list of events inside the match record's JSON** (`PerformanceEntry.metrics`). No schema
  change, but a shot map across a season would read every match record, events would have to
  be validated inside the totals' schema, and a tag would need a match record to exist first.
  Rejected.
- **Live tagging from the sideline with a match clock, no video.** Simpler, but a tag cannot be
  checked again, and the user chose video. A live mode can be added later on the same table.
- **Computer vision** to tag events automatically. Not feasible to make reliable on phone
  recordings of youth matches within this project; a possible later study.

## Consequences

- One more core table. It holds only what every sport's events share; table tennis has no
  event types yet and its tagging is future work (points by type: serve, winner, unforced
  error).
- A match is identified by club, date and label, not by a match table. When fixtures arrive
  (FootyStats), events can point at a match row instead. TODO.
- Tagged data is approximate by nature, and the screens say so ("a tag is a person's reading
  of the video").
- The synthetic data has no tagged events yet, so the shot map appears only for players whose
  matches someone has tagged. Seeding plausible events is a separate task, because it touches
  the generator and so the published numbers.
