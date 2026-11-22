# 0009. FootyStats as the professional tier's source: basic seasons

Status: accepted 2026-11-19.
Date: 2026-11-19

## Context

FootyStats is the professional tier's real source: the Egyptian Premier League will come from
it. Until the subscription is bought, its public test key unlocks the England Premier League
2018/19 to 2024/25 and Liga MX 2019/20, in exactly the format the Egyptian league will arrive
in. StatsBomb open data (decision 0008) is test data only: old seasons, and a kind of data
(every event with pitch coordinates) the real source will never have.

The pro tier's records were designed around richer data than FootyStats publishes:

- A player's season (`football.season_aggregate.v2`) requires 26 statistics. FootyStats'
  player data has appearances, minutes, goals, assists, penalties, cards, clean sheets and goals
  conceded. It has no player xG, shots, passes, tackles, dribbles or duels.
- A team's season (`football.team_season.v1`) required set-piece goals. FootyStats publishes
  team xG, shots, possession and goal times per match, but not how goals were scored.
- Match-by-match data (team xG, shots, possession, odds per match) has no table.

## Decision

1. **A second, basic player season record**, `football.season_basic.v1`, in the football sport
   module: exactly the fields FootyStats publishes, nothing filled in. It is configuration, not a
   database change (the shared-core rule, decision 0001). The profile's performance table shows
   it like any other period. Views that need the deep statistics (the scouting report, judged
   league seasons, "plays most like", team gap candidates) do not compute anything from it, and
   say why rather than "no seasons on record".
2. **Set-piece goals become optional** in `football.team_season.v1`. A statistic a source does
   not publish is unknown, not zero: team gap analysis leaves a team out of a ranking whose
   inputs it lacks (`app/sports.py`), instead of ranking it last. The published gap-analysis
   numbers did not move (`python -m ml.run_gap_eval`, 2026-11-19).
3. **Team seasons are computed from the matches** and checked against FootyStats' own season
   totals (matches, wins, draws, losses, goals for and against, clean sheets). A mismatch rejects
   the team season. On the downloaded seasons all 159 agreed exactly.
4. **Matches are not stored in the database yet.** Work that needs them reads the downloaded
   files. A matches table is a schema change and waits for a screen that needs it.
5. **Like StatsBomb, the data never enters the repository.** `fetch.py` downloads to a folder
   outside it and refuses one inside; tests use invented rows.

## Consequences

- The app runs on a basic source and a rich one side by side. Anything new for the pro tier
  must say which inputs it needs, and must work from the basic record if it is meant to run on
  the Egyptian league.
- FootyStats gives four position groups (goalkeeper, defender, midfielder, forward). Only a
  goalkeeper maps to one of the platform's position codes, so outfield players are stored with
  no position rather than a guessed one. Position-group comparisons for them use the source's
  four groups.
- A player who is in two sources (StatsBomb and FootyStats) is two records. Matching people
  across sources is not built.
- Whether the paid FootyStats plan adds deep player statistics is unverified; if it does, they
  go into the v2 record and everything built on it runs unchanged.

## Update (2026-11-22): team gap analysis on basic seasons

Point 1 listed team gap candidates among the views that compute nothing from the basic record.
Team gap analysis now covers a league with basic player seasons only, on the statistics the
record has: squad coverage and candidates on talent estimates of non-penalty goals and assists
per 90, and candidates only for a weakness in making chances. Every other weakness says the
basic data has no statistic for it (decision 0003, "Leagues with basic player data"). The
scouting report, judged league seasons and "plays most like" still need the deep statistics.
