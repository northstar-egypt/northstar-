# 0008. StatsBomb open data for the professional tier

Status: accepted 2026-11-14.
Date: 2026-11-14

## Context

The professional tier (decision 0003) was built on a synthetic Egyptian league shaped like
FootyStats, waiting for the FootyStats subscription. A probe of the real FootyStats API with its
free test key (2026-11-14) showed that its player data is 65 basic fields: minutes, goals,
assists, cards. It has no per-player expected goals, passes, tackles, dribbles or duels on any
paid plan, and the scouting report, team gaps and radars need exactly those.

The project supervisor allowed data from other leagues. StatsBomb publishes event data (every
pass, shot, tackle and carry, with pitch coordinates) free for research and education at
github.com/statsbomb/open-data. The team read and accepted its licence on 2026-11-14.

What the open data actually covers was checked before anything was built, because the obvious
reading of its competition list is wrong: the recent league seasons (Bundesliga 2023/24, Ligue 1
2021/22 and 2022/23, La Liga 2016 to 2021) hold one club's matches, not the league's. The
complete men's league seasons are all 2015/16.

## Decision

1. **The data loaded** (about 5.3 GB of JSON): the complete 2015/16 seasons of the Premier
   League, La Liga, Serie A and Ligue 1 (1,517 matches); the World Cups of 2018 and 2022; and the
   2023 African Cup of Nations, which has Egypt's matches. Egypt also played three matches at the
   2018 World Cup.
2. **It never enters the repository.** It is real data about real players. The raw files live
   outside the repository (`D:/northstar-data/statsbomb` on the machine that loaded it) and only
   in local databases. Tests use an invented match in StatsBomb's format.
3. **It lands in the records the platform already has**, so every existing analysis runs on it
   unchanged (`data/pipelines/statsbomb`, `source = 'statsbomb'`):
   - a player's season in `football.season_aggregate.v2`, the format the synthetic league uses;
   - a team's season in `football.team_season.v1`;
   - every shot in `match_event` (the table coaches' tags use), with its xG.
   No database schema change was needed. How each count is made (what is a tackle, a duel, a
   key pass) is written down in `data/pipelines/statsbomb/aggregate.py`.
4. **Expected goals is a measure, not a detail.** Details are what a coach picks from a list
   (decision 0007). A shot's xG is a number the data supplies, so event types gained `measures`
   in the sport module (`events.types.shot.measures.xg`, 0 to 1), checked when it loads. The
   tagging screen and a coach's tags are unchanged; the events API returns measures separately.
5. **Players have no date of birth.** StatsBomb's open data does not publish one. Players are
   recorded as adults (`is_minor = false`), since these are senior professional competitions,
   and every age-based view says the age is unknown. The scouting report grades a player with
   no date of birth only when the platform records them as an adult.
6. **Consent rows name the licence.** The access rules read consent. For this data the basis is
   StatsBomb's licence, not the player's own agreement, so the rows say so
   (`granted_by = 'statsbomb_open_data_licence'`) and are never presented as a player's consent.
7. **Seasons are compared only within one competition.** A World Cup is not the season after a
   league season. The breakout detector and season trends now pair a season with the previous
   one in the same competition, from that competition's own first season. With one competition
   per player, as in the synthetic league, the pairs are exactly as before: `run_pro_eval`,
   `run_report_eval` and `run_gap_eval` print identical output before and after.
8. **The report grades the latest season it can.** A player's latest season may be a tournament
   with too few minutes to grade (Salah: 148 minutes at the 2023 African Cup of Nations). The
   app's report takes the latest season with enough minutes and enough peers instead. The
   evaluation keeps its old rule, so its published numbers do not move.

## Checks on the load

- The goals counted from the events equal the published score in all 1,697 matches.
- Known results come out right: Leicester City 81 points in the 2015/16 Premier League; Suárez
  40, Higuaín 36 and Kane 25 league goals; Mbappé 8 goals at the 2022 World Cup; Salah 14 goals
  and 6 assists for Roma in Serie A 2015/16.
- Every row passes the sport module's schema and invariants. Every country maps to an ISO code.

## Known limits

- **Ligue 1 2015/16 has 377 of its 380 matches.** Ibrahimović shows 36 league goals; he scored 38.
- **No consecutive complete seasons**, so the breakout detector stays on the synthetic league,
  and scouting report v2 can be checked only within 2015/16 (split-half), not against the
  following season.
- **2015/16 is nine years old.** It is the data for building and grading methods, and for a
  real population to compare players against, not a current scouting view.
- **Not every pass is stored.** Only key passes (a pass that led to a shot) are events; the
  other 1.7 million passes are counted into the season totals and the touch map, not kept one
  by one. A pass network or progressive-pass map would need them.
- **Possession** in a team season is the share of in-play time in each team's possessions, from
  StatsBomb's own possession numbering.

## Added for the scouting report (2026-11-16)

The approved scouting-report design draws a shot map, a key-pass map and a heat map, grades a
chosen season, and lists players who play alike. What that added:

- **Key passes as events**: one `match_event` per pass that led to a shot, type `pass`, outcome
  `key_pass` or `assist`, with three new measures on the pass type: where it arrived (`end_x`,
  `end_y`, 0 to 100) and the xG of the shot it set up (`xa`).
- **A touch map per season**: `football.touch_map.v1`, a performance record of 96 counts, the
  player's events with a location on a 12 by 8 grid (zone `z<row>_<col>`, row 0 the left
  touchline as the team attacks, column 0 its own goal line, each zone 10 by 10 of StatsBomb's
  120 by 80 pitch). The heat map is drawn from it. Kept as counts, not 3.5 million events. Its
  period is marked `"showOnProfile": false`, a new module setting, so the profile does not list
  96 zone counts as a table of records.
- **Wording for what stands out**: `scoutingReport.phrases` in the football module, a few plain
  words per statistic ("gets into scoring positions"), so the report's three lines (what stands
  out, the weakest area the role needs, a caution about finishing or minutes) are read from the
  numbers and stay sport-specific configuration.
- **Players who play alike**: `ml/pro/style.py`, cosine similarity of the position group's
  statistics per 90, each standardised across the pool, among seasons with 900 or more minutes
  from the same data source, so real players are compared only with real players. Style, not
  level. Not yet evaluated; the check to run is whether a player's first half season finds
  their own second half among the nearest.
- **A chosen season**: the report takes `competition` and `season`; without them it reports the
  latest season it can grade, as before.

## NorthStar's own xG in the app (2026-11-16)

The loader now trains NorthStar's expected-goals model (ml/xg, graded in ml/README.md,
"Expected goals") on the 2015/16 league shots as it loads, and every xG the app shows is that
model's: each shot's (`match_event.details.xg`), and through it players' xG, npxG and xA, teams'
xG for and against, percentiles, scouting reports and finishing against expected.

- League shots get out-of-fold values, so no player's xG comes from a model that saw their
  match; tournament shots get the model fitted on all four leagues; penalties get the training
  leagues' conversion rate.
- StatsBomb's own value stays beside each shot as a measure, `xg_statsbomb`, so the two can be
  compared and the change undone: `--statsbomb-xg` loads StatsBomb's values instead.
- The scouting report says whose xG it shows (`pitch.xgModel`), and the page credits it.
