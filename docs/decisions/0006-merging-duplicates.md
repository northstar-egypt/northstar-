# 0006. Merging duplicate records: confirm merges, and a merge can be undone

Status: accepted 2026-10-25.
Date: 2026-10-25

## Context

The duplicate detector finds the same child entered twice, most often by a second academy
that typed a shorter name. Until now a reviewer who confirmed the case on the integrity board
only recorded a decision. Both records stayed active: the boy appeared twice in search, his
history was split across two profiles, and the board's button said "merge" while nothing
merged.

The schema already had the destination. `player.status = merged` with `merged_into` pointing
at the record kept; every list, search and cohort leaves merged records out; the table tennis
rating already follows `merged_into`. What was missing was the operation, and an answer to the
question `docs/schema.md` left open: is a merge reversible?

## Decision

1. **Confirming a duplicate merges the two records**, in the same transaction as the decision
   (`apps/api/app/services/merge.py`). Dismissing it, or asking for more information, merges
   nothing.
2. **The record kept** is the one with more measurements (the older one on a tie), unless the
   reviewer picks the other on the board.
3. **What moves to the record kept:** measurements, performance records, other players'
   records that name the merged one as their opponent, tagged match events, academy links and
   a linked player account.
4. **Conflicts keep the record kept's own row.** The same metric on the same day stays on the
   merged record; nothing is averaged. A performance record the kept record already has (same
   sport, period, opponent and figures) stays too, and so does a match between the two records
   themselves, which moved would be a match against himself.
5. **Both academies keep him.** The merged record's academy link moves, unless the record kept
   is already at that academy, so no coach silently loses a player. If he really left one, the
   federation ends that link separately.
6. **Consent forms do not move.** A guardian signed for the registration in front of them. The
   record kept is governed by its own forms.
7. **A merge can be undone.** Its audit row (`player.merge`) lists every row it moved. Undo
   moves exactly those back, makes the record active again, reopens the case and any cases the
   merge closed, and writes `player.unmerge`. Undo needs a reason, like every decision, and
   only federation staff and admins can merge or undo. No schema change: the list lives in the
   existing audit log.
8. **A merged record leads to the one kept.** Its profile link answers 404 with the id of the
   record kept, but only when the caller may open that record, so the rule that a 404 reveals
   nothing still holds. The web app follows it. The record kept lists what was merged into it,
   with Undo for reviewers.
9. **The detector run leaves merged records alone.** The duplicate detector does not read
   status, by design, so its evaluation cannot score by reading the answer key. `write_flags`
   skips pairs where either record is merged, and the clean-up that closes cases against
   merged records now also closes cases that name one as the second record. The detector and
   its published numbers are unchanged.

## Consequences

- Rehearsing the demo no longer uses up a demo player: once merged, the second entry is out of
  search, and the next rehearsal can register the same boy again.
- Undo restores what the merge moved, not later edits. A reading added to the record kept
  after the merge stays there on undo, because the merge did not move it.
- The forecast model is not refitted on a merge. It is fitted on the whole population, which
  one moved reading does not change, and refitting takes seconds. The caches that count
  players (cohort, concept filter, rating, similar players) are reset.
- Generated data has merged records with no audit row, because they were made merged. Their
  profiles say "merged before merges were recorded", and they cannot be undone.
- Three cases on the seeded board named an already merged record; the next detector run
  closes them.
