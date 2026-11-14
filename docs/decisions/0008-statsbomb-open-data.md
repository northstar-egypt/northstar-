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
- **Only shots are stored as events so far.** Passes, carries and defensive actions, for pass
  maps and heat maps, are the next step and need a decision on volume (about 1.7 million passes).
- **Possession** in a team season is the share of in-play time in each team's possessions, from
  StatsBomb's own possession numbering.
