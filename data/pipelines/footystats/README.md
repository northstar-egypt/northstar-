# FootyStats

The professional tier's real source. FootyStats publishes league, team, match and player
season statistics through an API (https://api.football-data-api.com). The Egyptian Premier
League will come from here once the subscription is bought; until then the team develops on
the seasons FootyStats' public test key unlocks, which arrive in exactly the same format.

Built so far: **downloading into a local cache** (`fetch.py`). Loading the cache into the
database is the next step.

## Download

```bash
python -m data.pipelines.footystats.fetch --cache-dir D:/northstar-data/footystats
```

- The key is read from `FOOTYSTATS_API_KEY`, or from the repository's `.env` if the variable
  is not set. `.env.example` has the line; never commit a real key.
- With no `--season-id` it downloads every season the key unlocks; `--season-id 12325` (repeat
  it for more) downloads only those. A season already in the cache is skipped, so an
  interrupted run can be started again; `--refresh` downloads it again.
- **The cache must be outside the repository.** The data is about real people, and the script
  refuses a folder inside the repo.
- The test key's 1800 requests an hour are shared with everyone who uses it. A full download
  is about 64 calls, one a second. Download once; everyone works from their own cache after.

What lands in the cache, per season (`<cache-dir>/<season_id>/`):

| file | endpoint | what it holds |
| --- | --- | --- |
| `players.json` | `league-players` | one row per player: age, birthday, height, weight, position (goalkeeper, defender, midfielder, forward), nationality, club, minutes, appearances, goals, assists, cards, clean sheets, conceded, penalties; overall and home/away |
| `matches.json` | `league-matches` | one row per match: date, teams, goals and goal times, each team's xG, shots, shots on target, possession, attacks and dangerous attacks, pre-match points per game, bookmaker odds |
| `teams.json` | `league-teams` with stats | one row per team, about 1,000 season statistics including xG for and against |
| `season.json` | `league-season` | league-level statistics |
| `tables.json` | `league-tables` | the standings |

Each file keeps the API's rows untouched, plus the endpoint, the parameters (never the key),
when it was downloaded and how many rows. `manifest.json` lists every season downloaded.

## What the test key unlocks, and what the data does not have

England Premier League 2018/19 to 2024/25 (season ids 1625, 2012, 4759, 6135, 7704, 9660,
12325) and Liga MX 2019/20 (2270).

**Not in the data:** player xG, shots, passes, tackles, or anything with a pitch location.
Team and match xG are there; player xG is not. Anything built on this source must work from
the fields in the table above.

Checked on the downloaded seasons (2026-11-19), worth knowing before using them:

- A player keeps the same id from season to season, so careers can be followed: between 370
  and 420 players appear in both of two consecutive Premier League seasons.
- Coaches appear in the players list (`position` "Coach"); leave them out.
- Between 74 and 179 players a season have 0 minutes (squad players who never played).
- Some players have no birthday (up to 59 in 2024/25), so their age is unknown.
- Liga MX 2019/20 has 63 cancelled matches (the season was stopped), with no xG.
