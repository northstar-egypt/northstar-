# Importing table tennis results

How official ITTF and WTT match results get into NorthStar, for federation staff and for
anyone on the team loading results into a local database. The code is
`apps/api/app/services/results_import.py`; the screen is **Oversight, Import table tennis
results** (federation and admin accounts).

## Why there is no scraper

The plan was a scraper for ITTF and WTT results. Checked on 2026-10-24:

- `results.ittf.link` and `ittf.com` answer automated requests with **403 Forbidden**, and
  `results.ittf.link/robots.txt` disallows `/api/` and `/ittf/`.
- `worldtabletennis.com` is a JavaScript application with no public API.

A scraper would have to get round those blocks, so there is none. Results are read in a
browser and copied by a person, which is how anyone may read them, and loaded with the
importer below.

## The file

A CSV, one row per match, as results are published. Download the empty template from the
import screen (it holds column names only).

| column | meaning |
| --- | --- |
| `date` | YYYY-MM-DD (required) |
| `event` | The event's name. Shown in the preview and kept in the audit log. |
| `player_a` | One player's name as published (required) |
| `player_b` | The other player's name (required) |
| `games` | Game scores from player A's side, e.g. `11-7, 9-11, 11-5, 11-8` (required) |
| `best_of` | 3, 5 or 7. Left empty, it is worked out from the scores. |
| `player_a_id`, `player_b_id` | A player's NorthStar id, only when their name matches more than one registered player |

From the scores the importer works out sets won and lost and points won and lost, which is
what the table tennis rating uses. Service winners and unforced errors are not in published
results and are left out; nothing is estimated.

## What happens to each row

- **Names** are matched to registered table tennis players by sound, in Arabic or Latin
  spelling, so `ELSAYED Ahmed` finds `أحمد السيد`. A name typed exactly wins over names that
  only sound alike.
- **Both players registered:** each gets a match record naming the other, so the match
  counts toward both ratings.
- **One registered:** that player gets a record, and **nothing** is stored about the other
  player, who may be a child with no consent form on NorthStar.
- **Neither registered:** refused. Add the players first (Squad, Import from spreadsheet).
- **Refused, with the reason:**
  - a game that is not finished (to 11, by two);
  - a match with games after it was decided, or no winner;
  - a date in the future or before a player was born;
  - a man against a woman;
  - an ambiguous name with no id;
  - a cell that looks like a spreadsheet formula.
- **Skipped as a duplicate:** a match already on record (same players, date and score), or
  repeated in the file. Importing the same file twice is safe.

Nothing is saved by the preview. Import checks the file again from scratch and saves every
ready row in one transaction, with one audit record.

## Never commit the files

Real results are real people, many of them children. The CSVs stay on your machine or in your
local database, never in the repository, not even as a test fixture (CLAUDE.md). The tests in
`apps/api/tests/test_results_import.py` use made-up names and scores.

## Not yet

- The event is not stored with the match: the match record has no field for it, and adding
  one is a schema change. TODO.
- Doubles and team events are not imported; one row is one singles match.
