# 0003. Team gap analysis: what a team lacks, and which players fill it

Status: accepted (design). One schema question is open, see "Open decisions".
Date: 2026-09-29

## Context

The pro tier ingests Egyptian Premier League data from FootyStats but does nothing with it
beyond showing it. The question a club analyst, a national team coach or a federation scout
actually asks of that data is: **where is this team weak, and which available players are
strong exactly there?**

The core of NorthStar stays national youth-development infrastructure. This is the pro
analytics branch that sits beside it. It also connects the three football tiers: the
candidates for a gap can come from the Egyptian league (pro tier) or from Egypt-eligible
players abroad (diaspora tier), and a youth player's trajectory can later be read against
the same profiles.

### What the data supports

Checked against FootyStats pages for the Egyptian Premier League, 2025/26 (Zizo's player page
and Al Ahly's team page). The API itself must still be checked field by field once the
subscription is live, because some website fields may be premium-only or website-only.

- **Player, per competition and season:** each stat as a total, per 90 minutes, and league
  percentile. Minutes, starts, goals, xG, non-penalty xG, shots (on and off target),
  conversion, assists, xA, passes and completion, key passes, crosses, dribbles, times
  dispossessed, tackles, interceptions, ground and aerial duels, dribbled past, clearances,
  shots blocked, cards, fouls, penalties. Also an estimated salary and an average rating.
- **Team, per season, overall, home and away:** points per game, xG for and against per
  match, goals scored and conceded, clean sheets, possession, shots and conversion, fouls,
  penalties, goal timing in 10 and 15 minute bands, first versus second half, set pieces.
- **Not available:** shot or event locations, heat maps, progressive passes or carries,
  pressing, tracking or physical data. Player data appears to be season totals, not per
  match.

## Decision

Build team gap analysis as three explainable steps, each shown to the user with its numbers.

1. **Team profile.** For each team, rank every team metric against the other teams in the
   same league and season. A metric in the bottom third is a candidate weakness. Each metric
   has a declared direction (more xG against is worse), kept in config next to the sport
   module, not in code.
2. **Squad coverage.** For each position group (from the football module's roles), show who
   plays the minutes and their per-90 league percentiles. This shows where the team relies
   on one player, or where the regulars sit in the bottom third of the league.
3. **Candidates.** Rank players outside the team whose percentiles are high on the
   attributes linked to the weakness. The link from a team weakness to player attributes is
   a short, hand-written mapping in config (for example, low shot conversion maps to
   non-penalty goals minus npxG, conversion and shots on target per 90). A weakness with no
   honest player-level counterpart, such as conceding late in games, is shown as a finding
   with no candidates rather than forced onto a stat.

Two modes:

- **Club mode.** The needs come from step 1.
- **National team mode.** The federation picks the needs by hand (for example, "left back:
  crosses and aerial duels"), because a national team plays too few matches for its own
  team stats to mean much. The candidate pool is every Egypt-eligible player, at home and
  abroad.

### Where the data lives (shared core, pluggable sport modules)

- Clubs and the national team are already `Organization` rows (`club`, `national_team`),
  with the FootyStats id in `external_ids`.
- **Player season stats** go into `PerformanceEntry` using a new version of the football
  module's season aggregate, `football.season_aggregate.v2`, which adds the fields above.
  That is a config change in `packages/shared/sports/football.json`, exactly what the sport
  modules exist for. No new player columns.
- **Team season stats** need a home. See "Open decisions".

### Honesty rules (the project's standing rules, applied here)

- **Minutes next to every per-90 figure,** and a minimum (starting at 900 minutes, to be set
  by the reliability check below, not by taste) before a player is ranked at all.
- **Percentiles are within one league.** A 90th percentile in Egypt is not a 90th
  percentile in Germany. National team mode shows each candidate's league next to every
  number and never ranks across leagues as if they were one population.
- **Salary is FootyStats' estimate.** It is labelled as an estimate and is not used for
  ranking.
- **No invented fit score.** The screen shows the percentiles that made a player a candidate,
  not a single opaque "fit %".

### How it is checked

There is no answer key for "the right signing", so this is not scored like the detectors.
What can be measured, and will be reported in `ml/README.md`:

- **Split-half reliability.** Compute team and player percentiles from the first half of the
  season and from the second half, and measure how well they agree, as a function of minutes
  played. That is what sets the minimum minutes, and it says which team weaknesses are
  stable enough to act on.
- **Unit tests on synthetic data** for the percentile maths, the direction of every metric,
  and the mapping, using a synthetic league from `data/pipelines/synthetic` (real FootyStats
  data never enters the repo or its tests).

## Consequences

Positive:
- The pro tier does something with the data it pays for, and the three football tiers meet
  in one feature.
- It reuses the scout search and comparison screens rather than adding a parallel product.
- The new player fields are a sport-module version, which exercises the architecture instead
  of working around it.

Negative / trade-offs:
- It is football only, so it adds depth but no evidence that the engine is multi-sport.
  Table tennis work must not be displaced by it.
- It changes the locked scope, so Chapters 1 and 3 of the thesis need to mention it.
- It depends on the FootyStats subscription and on the API matching the website.

## Open decisions (ask before building)

1. **Where team season stats are stored.** Proposed: one new table,
   `organization_season_stat` (organization, sport, competition, season, source, `metrics`
   JSONB, `schema_ref`), mirroring `PerformanceEntry` so team metrics are validated by the
   sport module (`football.team_season.v1`) like player metrics are. This is a schema change
   and a migration, so it needs the team's approval.
2. **Who sees it.** Proposed: scouts and federation staff, with no new role. A club analyst
   role can come later if needed.

## Alternatives considered

- **A single "fit score" per candidate.** Rejected: it hides which numbers drove it, and the
  weights would be invented.
- **Similarity to an existing player ("find me another Zizo").** Kept as a separate feature
  (the planned embedding similarity search); it answers a different question.
- **Team stats as JSON on `Organization`.** Rejected: team stats change every season and
  per competition, and one mutable blob would lose that history.
