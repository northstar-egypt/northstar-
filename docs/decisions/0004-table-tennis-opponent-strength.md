# 0004. Table tennis opponent strength: who a match was against, and a rating built from it

Status: accepted 2026-10-08, with the recommended answer to every open decision.
Date: 2026-10-08

## Context

A table tennis match row today records the score (sets, points, service winners, unforced
errors) and nothing about the opponent. The only opponent field is the core column
`PerformanceEntry.opponent_org_id`, which names a club. That fits football, where a club
plays a club, and says almost nothing in table tennis, where a player plays a player.

So every table tennis number a scout sees is a result without context. A 70% match win rate
against local juniors and a 45% win rate against the national top ten look the same, and the
first one ranks higher in search. For the sport that is meant to prove the engine is not
football-only, that is the weakest point: the football side has xG against actual, age
curves and forecasts, while table tennis has win percentages.

The synthetic data has the same hole. In `data/pipelines/synthetic/performance.py` the chance
of winning a point depends only on the player's own ability. No opponent exists, so nothing
built on the data could learn about opponents even if the schema allowed it.

Size today, default seed: 32 table tennis players (21 boys and men, 11 girls and women, 17
minors) and 638 match rows, 8 to 33 per player.

## Decision (proposed)

### 1. Record who the opponent was

A match row says who was on the other side of the table, when that player is registered on
the platform, with a nullable `opponent_player_id`. Where to put it is open question 1. The
recommendation is a **core column**, next to `opponent_org_id`, because:

- It is not table tennis specific. Every one-on-one sport the platform could add (tennis,
  badminton, squash, judo, wrestling) has a player as the opponent. This is the same test the
  shared-core principle uses: a field that every sport of a kind needs is core.
- It is a reference to another player, so it should be a foreign key. In the JSON metrics it
  could point at a player who does not exist, and a duplicate merge (`merged_into`) would
  have to rewrite JSON in other players' rows to keep it correct.

When the opponent is **not** on the platform, the row records no identity at all. Opponents
are often children, and a child who is not registered has no signed consent form. Storing
their name in another child's match row would be storing personal data about a minor
without consent. The match still counts toward the player's results; it just cannot count
toward a rating.

### 2. Compute a rating from the matches, with its uncertainty

From the registered-against-registered matches, the platform computes a rating per player,
using **Glicko-2** (open question 2). Glicko-2 is a well-known rating system (online chess
sites such as Lichess use it) and it carries a rating deviation, a measured
uncertainty. That matters here because of the project's first rule: a rating built from
four matches is not known yet, and the profile must say so rather than show a confident
number. With Glicko-2 the uncertainty comes from the model itself, not from a cut-off picked
by hand.

- The algorithm is about 80 lines and is written in `ml/rating/` with no new dependency,
  following how `ml/forecasting` is built.
- The API runs that same code on the database (`apps/api/app/services/rating.py`, the
  pattern `services/forecast.py` already uses), so the rating on screen is the rating whose
  accuracy is published.
- Ratings are computed in date order over rating periods (one month), so a rating at a date
  only uses matches before that date. The evaluation depends on that.

### 3. Show it, and only when it means something

- **Profile:** rating with its range (rating plus or minus two deviations), the number of
  rated matches behind it, and a plain-words reading ("strong for their age group" only if the
  range supports it). Shown only below a deviation threshold. Above it the profile says
  "not enough rated matches yet (n of about 10)" and draws nothing.
- **Match list:** each match shows the opponent's rating at the time, so a loss to a much
  stronger player reads as what it is.
- **Search:** "beats strong opponents" and "high rated" become searchable concepts through
  the existing concept system (`apps/api/app/concepts.py`), with the same minimum-basis rule
  the other statistics use. The rating is a per-player value, not a ratio over one player's
  rows, so it needs a small extension to how the search reads statistics. That is in the
  build, not a sport module change.
- **Table tennis girls are few** (about a dozen per dataset). Ratings are computed over one
  pool, but the evaluation reports girls separately, and if their numbers are poor the
  README says so.

### 4. Make the synthetic data play real matches

The generator changes from "a player has results" to "two players played":

- Each match is generated once between two registered players and written as **two mirrored
  rows**: the winner's sets won are the loser's sets lost, and so on. Service winners and
  unforced errors are drawn for each side.
- The chance of winning a point comes from the **difference** in hidden ability between the
  two players, not from one player's ability alone.
- Opponents are chosen by gender and by closeness in recorded age (juniors mostly play
  juniors, as in real draws), **not by ability**. Choosing by ability would hand the rating an
  advantage over a plain win rate that the generator, not the method, created. This is the
  hardest fair setting for a rating.
- About a third of matches are against opponents **not** on the platform. Those produce one
  row, with no `opponent_player_id`, against an opponent drawn from the whole population.
- One registered match in eight is logged by only one of the two players, as it would be in
  real life.
- The existing planted table tennis fraud (a match both players won) stays.

### 5. Check it against the truth the generator knows

The generator knows every player's hidden ability, so the rating can be graded:

- **Ranking accuracy:** Spearman correlation between the rating and hidden ability, against
  two baselines: match win rate and point win rate. If the rating does not beat point win
  rate, that is the headline, not a footnote.
- **Prediction:** walk-forward, predict the result of each match from ratings computed only
  on earlier matches. Brier score and log loss against the same two baselines and against a
  coin flip.
- **Calibration of the range:** how often hidden ability sits inside the shown range.
- Tuned on seeds 101, 202 and 303, reported on others, as the project rule requires. A new
  `python -m ml.run_rating_eval` prints all of it, and the numbers go in `ml/README.md`.

## Consequences

- **Published numbers: none moved.** The generator draws from one shared random stream, so
  generating paired matches was expected to shift every draw after it. Table tennis matches
  now come from their own stream, which shifted the main stream once. Checked with
  `--seed-sweep 20260827 7 99 404 555` on both evals, before and after: the forecast output is
  byte-identical (heights are drawn before matches), and in the detector output the only lines
  that changed are the "any self-submitted row" baseline and the number of injected impossible
  rows (which still score 1.000). Neither is quoted in `ml/README.md`.
- A migration (`0003_add_opponent_player`), a schema doc update (`docs/schema.md`, which
  already lists "is `opponent_org_id` enough?" as an open question; this answers it for
  one-on-one sports).
- Real data fits later without a redesign: ITTF and WTT results (the scraper on the board)
  name both players, so a scraped match maps an opponent to a registered player when there is
  one, and to no identity when there is not.
- The rating is new graded material for the ML chapter, and the first analytic that exists
  for table tennis and not for football.

## Open decisions (ask before building)

1. **Core column or JSON field for the opponent?** Recommended: core column
   `opponent_player_id` (UUID, foreign key, nullable), with a migration. The alternative,
   an optional `opponent_player_id` string in the table tennis metrics, avoids a migration
   but loses the foreign key and breaks on merges. This is a schema change, so it needs a yes.
2. **Glicko-2 or Elo?** Recommended: Glicko-2, for the built-in uncertainty. Elo is simpler
   to explain but has no uncertainty, so the "not known yet" threshold would be a hand-picked
   match count.
3. **A new planted fraud case now, or later?** Mirrored rows make a new check possible: a
   self-submitted win whose opponent's own row records a loss to someone else, or a win over
   a registered opponent with no matching row. Recommended: later, as its own task, so this
   change stays one topic and the fraud numbers move only once for a known reason.
4. **Accept that published numbers move once** (see Consequences), reported in the PR with
   before and after.

## Build order (one PR each)

1. Generator: paired matches, own random stream, opponent field; re-run both evals and report
   the one-time shift. Includes the migration if open question 1 goes that way.
2. `ml/rating` and `ml.run_rating_eval`: Glicko-2, the three checks above, numbers in
   `ml/README.md`, including the ones that come out badly.
3. API and profile: rating with range, opponent rating per match, the "not enough rated
   matches" state; checked in Firefox.
4. Search concepts for rating.

## Alternatives considered

- **Store an external rating per match** (the opponent's ITTF ranking points at the time).
  Real scraped data has it for ranked adults, but many juniors have no ITTF ranking,
  ratings from different systems do not share a scale, and a self-submitted row can claim any
  number. Kept as a possible optional field once the scraper exists, not as the main signal.
- **Adjust win rate by the opponent's club** (using the existing `opponent_org_id`). Club
  strength is a weak stand-in for one player's strength, and the column means little in a
  sport played one on one.
- **A full Match entity** (one row per match, two participants). Cleaner in theory, but a
  much larger change to the core model, and football would need it too. Mirrored
  `PerformanceEntry` rows fit the current model and are what a federation export or a
  results scrape produces anyway.
