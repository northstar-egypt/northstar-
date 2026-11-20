# 0010. The identity engine proposes duplicate cases on the integrity board

Status: accepted 2026-11-20.
Date: 2026-11-20

## Context

The identity engine (`ml/identity`, team plan 7.2) finds records that are the same person
across scripts, without a date of birth and across data sources. Its first version (#117) was
graded on generated data only. Run on the demo database before wiring it in, it proposed 6,086
links, most of them plainly wrong: with no labels, its fit had learned "same first name" rather
than "same person". The fix (ml/README.md, "Player identity") brought it to 731 links on the
same database, of which 84 are certainly wrong (two records of the same source, StatsBomb, which
has one record per player). The precision of the rest is not known: there are no labelled real
pairs.

Duplicate cases already reach the integrity board from the duplicate rule (v1), and confirming
one merges the two records, with an undo (decision 0006). Two questions followed:

- whether the engine merges records itself or proposes them;
- how a review queue stays usable when one run adds hundreds of cases.

## Decision

1. **The engine proposes, a person decides.** Its links are raised as ordinary duplicate cases
   by `ml/write_flags.py`, detector `identity`, with the engine's probability as the case's
   confidence and what agreed and disagreed, in words, as its evidence. Nothing is merged without
   a reviewer's decision and reason. Each decision is the labelled real pair the engine does not
   have yet.
2. **One case per pair.** A pair both the rule and the engine find is one case (the same
   `dedupe_key`), with the engine's probability. A case already open is refreshed with the
   newer model's numbers; a dismissed one is not raised again.
3. **Fraud first.** The queue is ordered fraud, then anomalies, then duplicates; newest first
   within a type, and duplicates most probable first. On the demo database the engine raises
   about 700 cases, mostly the same professional in StatsBomb and FootyStats, and in a queue
   ordered by date alone they buried every fraud case about a child.
4. **Counts from the table.** The board's header and type chips show counts from
   `GET /integrity/counts`, and the chips filter the queue (`?type=`). The queue is cut at a
   limit, so counting the cases loaded understated a long queue. `?player=` lists the cases
   about one player, whichever record a pair is stored against.

## Consequences

- A reviewer can work through the professionals' cross-source pairs, and the federation's data
  gets one record per professional. The demo database then gains about 700 open cases.
- The board shows each identity case's probability. On generated data it is graded
  (ml/README.md); on real professionals it is not, and each case says so.
- TODO(ml): read the reviewers' decisions back as labelled pairs, and measure the engine's
  precision on real data from them, the way ml/feedback.py reads decisions back for the late
  bloomer and age misrepresentation detectors.
