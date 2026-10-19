# What changed in the results, 2026-10-15 to 2026-10-19

For anyone updating the thesis chapters, the slides or the defence answers. Between 2026-10-15
and 2026-10-19 almost every headline number moved, most of them down, each for a reason that
makes the project more honest. This page lists every number that is likely to be quoted
somewhere, its old value, its value now, and why it moved. The full detail, with the old
numbers kept beside the new ones, is in `ml/README.md`. If a number here and `ml/README.md`
ever disagree, `ml/README.md` wins.

## The five changes

| PR | what it did | effect on the numbers |
| --- | --- | --- |
| #49 | Every synthetic child now reaches the growth spurt at a slightly different age (spread 0.9 years), as real children do. Before, every unplanted child grew on the same timetable. | Late bloomer and fraud **down**, forecasts slightly worse. The old numbers were flattered by data that was too clean. |
| #50 | A growth-timing late-bloomer detector (SITAR-style) was built and tested. | **Lost** to the existing rule, kept as a measured alternative. No number moved. |
| #51 | The age-fraud rule now needs performance evidence as well as growth before it accuses anyone. | Fraud **up**, false age accusations cut by more than half. |
| #55 | Table tennis: a result the opponent's own record contradicts is flagged. Three such cases planted per dataset. | Fraud **up** again; table tennis rating moved in the third decimal. |
| #56 | Retuning the late-bloomer thresholds was tried on the tuning seeds. | **Not adopted** (noise). No number moved. |

## The defence sentence

Old:

> Of the late bloomers a size-based cut would have released, the system flagged about half of
> those it had measured at least three times, against about one in six of the other small
> players.

Now:

> Of the late bloomers a size-based cut would have released, the system flagged about four in
> ten of those it had measured at least three times, against about one in five of the other
> small players. It could not flag any it had measured fewer than three times, and that was
> more than half of them.

The gap is smaller but real: the confidence intervals do not overlap (31 to 51% against 16 to
30%). The second sentence did not change and is still the main practical finding: measure
every player at intake and every few months, which the coach dashboard now asks for.

## Every headline number, old and now

Five reported seeds unless stated; "20 seeds" is the five plus 1000 to 1014. Tuning seeds are
101, 202 and 303.

| number | old (2026-10-15) | now | moved by |
| --- | --- | --- | --- |
| late-bloomer F1, 5 seeds | 0.649 | **0.567** | #49 |
| late-bloomer F1, 20 seeds (the one to quote) | 0.555 | **0.479** | #49 |
| late-bloomer F1, tuning seeds | 0.639 | **0.557** | #49 |
| fraud F1, 5 seeds | 0.747 | **0.744** | #49 down to 0.642, #51 up to 0.701, #55 up to 0.744 |
| fraud F1, 20 seeds (the one to quote) | 0.726 | **0.769** | #49, #51, #55 |
| fraud F1, tuning seeds | 0.767 | **0.830** | #49, #51, #55 |
| duplicate F1, 5 / 20 seeds | 0.973 / 0.961 | 0.973 / 0.961 | unchanged |
| age-fraud rule, 20 seeds: caught / false accusations | 92 / 57 | **94 / 49** | #49 made it 83 / 112, #51 brought it to 94 / 49 |
| age-fraud rule F1, 20 seeds | 0.559 | **0.582** | #49, #51 |
| isolation forest (age fraud), 20 seeds: caught / false accusations | 112 / 102 | **95 / 151** | #49; the forest reads growth only |
| backtest, 1000 players: late bloomers flagged at the cut (measured 3+ times) | 47%, 40 of 86 | **41%, 35 of 86** | #49 |
| backtest, 1000 players: other small players flagged | 16%, 23 of 142 | **22%, 31 of 140** | #49 |
| backtest: late bloomers measured fewer than 3 times, flagged | 0 of 117 | 0 of 113 | unchanged in substance |
| height forecast MAE under 18, cohort velocity | 0.86 cm | **0.94 cm** | #49 |
| height forecast MAE under 18, XGBoost (what the profile draws) | 0.80 cm | **0.86 cm** | #49 |
| forecast MAE, girls (XGBoost / cohort velocity) | 1.25 / 2.26 cm | **1.15 / 1.96 cm** | #49 |
| forecast MAE, planted late bloomers (XGBoost / cohort velocity) | 1.04 / 1.20 cm | **1.01 / 1.25 cm** | #49 |
| forecast 80% band coverage, 5 seeds | 79.5% to 82.5% | **78.2% to 80.4%** | #49 |
| table tennis rating, Spearman with hidden ability (girls / boys) | 0.907 / 0.893 | 0.907 / 0.893 | unchanged |
| table tennis rating, log loss against point win rate | 0.564 / 0.578 | 0.564 / 0.577 | #55, third decimal |
| table tennis rating, range covers the truth | 168 of 171 | 168 of 171 | unchanged |
| relative age audit, closest call | late bloomer, p = 0.12 | age-fraud rule v1, p = 0.12; v2 is p = 0.28 | #49, #51 |

## New results to add

- **Table tennis result tampering** (#55): over 20 seeds the rule caught **60 of 60** planted
  cases with **18 false alarms**, every one the honest opponent in a match where both rows were
  self-submitted. Fraud F1 rose on 16 of 20 seeds, stayed level on 1 and fell on 3. The first version caught 58 of
  60; both bugs were found on reported seeds and the README says so. Football has no
  equivalent check: it exists because a table tennis match is logged by both players.
- **Growth-timing late-bloomer detector** (#50): F1 0.477 against the rule's 0.567, catching
  more late bloomers (44 against 36) but with three times the false alarms (69 against 21). A
  negative result, kept and explained.
- **Late-bloomer retune** (#56): the best gain on the tuning seeds (+0.03) came from nearly
  removing the growth check; the version that keeps it was better on two seeds and worse on
  the third by about one case. Not adopted.
- **Early maturers look like age cheats** (#49): with realistic growth timing, the growth-only
  age-fraud rule's false accusations doubled (57 to 112). That is why #51 requires a second
  line of evidence, and why every age flag is a question for a reviewer, never a finding.

## Claims to remove

- "Simulated release at 14 costs about a sixth of the observed catch-ups (46 to 38)." With
  realistic growth timing it no longer appeared (34 to 33). The README dropped the claim.
- Any statement that the integrity board shows a confidence for each flag. No detector
  produces one; since #57 the board says "rule, no score".
- "The fraud label covers two kinds of fraud, 14 cases per dataset." It is now three kinds, 17
  cases (9 age, 5 arithmetic, 3 table tennis result tampering).

## Unchanged and safe to quote

Duplicate detection (0.961 over 20 seeds, with the caveat that the generated problem is easy);
the table tennis rating's ranking and calibration; the Firefox end-to-end demo flow (22 of 22
on 2026-10-19 against the rebuilt app and current data); the late-bloomer figure
(`docs/figures/late-bloomer.svg`, same player, caption rates updated).
