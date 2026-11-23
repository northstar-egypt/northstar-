# 0011: Squad Lab, a line-up builder with chemistry scores

Status: proposed (draft PR), 2026-11-23

## What it is

A screen at `/squad-lab` where a user picks a formation (4-3-3, 4-4-2, 4-2-3-1), puts players
in it and sees:

- a score for each player in his slot,
- a coloured line between each pair of neighbours (green, yellow, red, or grey when there is
  not enough data),
- a team score: one number per line (defence, midfield, attack), chemistry (the average link)
  and balance (the weakest line).

Managers (coaches) save squads for their club. Scouts and federation staff can try line-ups but
cannot save one and never see a club's saved squads.

## How the numbers are made

A rule of thumb, not a trained model. Nothing in `ml/README.md` changes. The rules live in the
sport module, `squadLab` in `packages/shared/sports/football.json`, so adding or changing a rule
is a config change, not code.

1. Each player's traits come from his own record: his latest league season
   (`football.season_aggregate.v2`), or failing that his match records from the last 12 months
   (`football.match.v1`). Minimum 450 season minutes or 270 match minutes.
2. Each trait is ranked as a percentile among players of the same family (academy, or
   everyone else) who play the position of the slot. A pool of fewer than 5 players gives no
   percentile.
3. A link uses the traits that partnership needs, listed per pair of position groups, and
   averages the percentiles. If either side has none of them, the link is unknown.
4. Only players with analytics consent are scored or ranked. A slot only shows a player the
   caller may see (`access.may_view`).

## Known limits (stated on screen)

- Goalkeepers are not scored: there is no goalkeeping data.
- Academy match records have no interceptions, clearances, duels or headers, so an academy
  defender is judged on tackles, passing and running only.
- Academy ranks are not adjusted for age.
- An academy 80 and a league 80 are not the same level: each is ranked within its own family.

## Open questions for review

1. **New table `squad`** (migration `0010_create_squad`). Draft PR #131 also uses `0010` and
   `0011`; whichever merges second renumbers its migrations.
2. **Coaches pick only from their own club.** Letting a manager try a player from another club
   would widen what a coach may see, which is an access rule change. Left as is; scouts and
   federation staff already see everyone.
