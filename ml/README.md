# ML and intelligence

Owner: intelligence/ML workstream. Model code and, just as importantly, the evaluation
harnesses that prove the models hit the graded targets. Reads from the database, writes
results (forecasts, flags, similarity, embeddings) back to it.

## Scope

- **Forecasting** of player trajectories with uncertainty bands. Per-position age curves.
  XGBoost as a challenger to the v1 model, see "Challenger models".
- **Detectors**: late-bloomer, fraud, duplicate. Measured with precision / recall / F1
  against the **planted ground truth** in the synthetic dataset. Built, see below.
- **Sustainability flags**: xG vs actual for football.
- **Similarity**: player embeddings via sentence-transformers.
- **Anomaly detection**: crosses over with the security workstream (self-submission fraud).
- **LLM assistant**: grounded natural-language queries via a local Ollama model. It phrases
  what the data and models already know; it does not invent player data.

## Evaluation is a first-class deliverable

We are graded on measured performance, so every model ships with a harness:

- **Detectors**: precision / recall / F1 against planted ground truth. Done.
- **Forecasts**: walk-forward validation, MAE / RMSE against two baselines (last-value and
  population-average). A model that cannot beat those baselines is not done. Height done,
  see below.
- **Access control** and **system demo** targets live with their workstreams, not here.

## Running the detector evaluation

```bash
pip install -r data/pipelines/requirements.txt
pip install -r ml/requirements.txt

# the dataset is gitignored, so generate it first
python -m data.pipelines.synthetic.generate

# score every detector against the answer key
python -m ml.run_eval

# write the numbers out as JSON as well
python -m ml.run_eval --json out/detector_scores.json

# generate and score several datasets, to see how much the headline moves
python -m ml.run_eval --seed-sweep 20260827 7 99 404 555
```

Run from the repository root. Tests: `pytest ml/tests`.

To put the detectors' findings in front of users, write them to the database:

```bash
python -m ml.write_flags --dry-run   # report what would be written, roll back
python -m ml.write_flags
```

That is the batch job connecting `ml/detectors` to the application. Until it runs, the
integrity board is empty and the player profile's flag banner never appears, because the API
reads flags from a table rather than recomputing them per request. It is safe to rerun: a case
already raised is recognised rather than duplicated, and a case a reviewer dismissed is not
raised again. See `docs/schema.md` under Flag for the `dedupe_key` that makes that work.

On Windows the player names are Arabic, so a console that is not already UTF-8 will fail
on the error-analysis output. Set `PYTHONIOENCODING=utf-8` before the command.

## Results, v1

**Every number in this file was re-measured on 2026-09-29**, when football became boys only
(girls now appear only in table tennis, about 5% of players, set by the sport modules'
`genders`). The generator changed, so every dataset changed, so every figure was re-run. Where
a finding changed materially the text says so, including where it got worse.

Five datasets, 212 players each. Headline F1 per detector:

| detector | 20260827 | 7 | 99 | 404 | 555 | mean | range |
| --- | --- | --- | --- | --- | --- | --- | --- |
| late_bloomer | 0.583 | 0.640 | 0.720 | 0.692 | 0.609 | **0.649** | 0.583 to 0.720 |
| fraud | 0.690 | 0.720 | 0.741 | 0.741 | 0.846 | **0.747** | 0.690 to 0.846 |
| duplicate | 1.000 | 0.957 | 1.000 | 0.909 | 1.000 | **0.973** | 0.909 to 1.000 |

Against the trivial baselines on the committed default seed, where flagging every player
scores F1 0.124 and random selection at the true prevalence scores 0.000 to 0.042.

Read those numbers with the following in mind.

**Thresholds were tuned on seeds 101, 202 and 303, and none of the five reported seeds is
one of them.** Tuning a threshold on the set you then report is the easiest way to publish
a number that does not survive contact with new data. Late-bloomer F1 averaged 0.639 on the
calibration seeds and 0.649 on the reported ones. Before the boys-only change the reported
seeds scored lower than the calibration ones (0.611 against 0.658); now they happen to score
higher. That is a property of these few seeds, not evidence the thresholds transfer
perfectly, and it is why the 20-seed figure below is the one to quote.

**Over more seeds the late-bloomer figure is lower.** The relative age audit below needed 20
datasets for its statistics, which also gave a wider look at F1. Over the five above plus
seeds 1000 to 1014 (none used for tuning), mean F1 is **0.555** for late bloomers, **0.726**
for fraud and **0.961** for duplicates. The five reported seeds are kind to the late-bloomer
detector (0.649 against 0.555). Quote the 20-seed figures when a single number is needed; the
five-seed table stays because the forecasts and backtest are reported on the same seeds.

**The spread is wide because the positive classes are small.** Fourteen late bloomers in
212 players means one case moving shifts recall by 7 points, and the 0.583 to 0.720 range
is mostly that. Every table the harness prints carries the raw TP/FP/FN counts and a Wilson
95% interval on recall, so nobody has to take a three-decimal F1 at face value.

**The duplicate score is high because the problem as generated is easy**, not because the
detector is clever. Clones always share sex and sport and sit within a few days of the
original's date of birth, so blocking plus normalised name matching finds nearly all of
them. The honest comparison is against the two controls in the same table: byte-identical
name matching gets recall 0.167, and reading the `merged_into` pointer, which is cheating
because it is the record of a merge a human already did, gets 0.417. Real duplicate
detection at national scale will be harder than this.

**The fraud headline mixes an easy problem with a hard one.** The harness splits them:

| fraud subtype | cases | F1 (default seed) |
| --- | --- | --- |
| implausible self-reported performance | 5 | 1.000 |
| age misrepresentation | 9 | 0.526 |

The perfect score on the first is arithmetic, not machine learning: those rows record more
goals than shots, more passes completed than attempted, and distances no human has run, or
for a table tennis carrier, matches both players won. That check belongs in ingest
validation rather than in a model, and it now is: the rule is the sport modules' own check
(`packages/shared/sports`), the same one ingest runs, so a new sport's rules reach the
detector without a change to it. The fact that it scores perfectly is a statement about the
generator. Age misrepresentation is the subtype that
matters, it carries 9 of the 14 cases, and at 0.526 it is doing little more than half the work
the headline 0.690 on this seed suggests (it was 0.632 before the boys-only change; see Known
limits for why young cases got harder). Anyone quoting the fraud number should quote this one
alongside it.

## Height forecasts, v1

```bash
python -m ml.run_forecast_eval                                  # the default dataset
python -m ml.run_forecast_eval --seed-sweep 20260827 7 99 404 555
```

**How it is validated.** Walk-forward over calendar origins, every 91 days from a year after
the first measurement. At each origin the forecasters see every measurement dated on or before
it, for every player, and nothing after. They forecast each player's readings up to a year
ahead. The origin is shared by all players rather than cut per player, because a per-player
cut would let the population curves learn from other children's later readings.
`test_forecasts_at_an_origin_cannot_see_past_it` rewrites everything after an origin and
checks that the forecasts made at it do not move, and it fails if the leak is put back.

**Headline**: mean absolute error in cm, players under 18 at the origin, five datasets:

| forecaster | 20260827 | 7 | 99 | 404 | 555 | mean |
| --- | --- | --- | --- | --- | --- | --- |
| baseline: last value | 3.29 | 3.17 | 3.20 | 3.22 | 3.07 | 3.19 |
| baseline: population average | 5.45 | 5.71 | 5.63 | 5.74 | 5.50 | 5.61 |
| **cohort velocity** | 0.87 | 0.86 | 0.88 | 0.82 | 0.88 | **0.86** |
| centile tracking | 1.60 | 1.86 | 1.61 | 1.84 | 2.17 | 1.82 |

Cohort velocity is the last reading plus how much the median child of that sex grows between
the two ages, with the growth curve learned from the training window. It beats last value by
73% and population average by 85%, on every seed. RMSE and a player-resampled 95% interval on
MAE are in the full output.

**No constant was tuned against these numbers.** Every threshold in `forecasting/models.py`
was set before the first run and none has changed since. That is also why the adult defect
below is reported and not fixed.

**The uncertainty band** is the band the player profile needs. It is an 80% interval around
cohort velocity built from the errors of earlier forecasts whose outcomes had already been
measured by the origin, so it is walk-forward as well. Observed coverage on the five seeds:
82.5%, 79.5%, 81.4%, 81.3%, 81.6%, at a mean width of about 2.7 cm. Close to the nominal 80% on
every seed, one of them half a point narrow.

Read the headline with these in mind.

**The problem as generated is smooth, so the model is close to the floor.** Synthetic heights
are a growth curve plus 0.55 cm of noise per reading. With that noise on both the last reading
and the target, a perfect forecaster still scores an MAE of about 0.62 cm. Cohort velocity
averages 0.69 up to three months ahead and 1.02 at six to twelve months. Real children are measured on
different stadiometers by different people and grow less tidily, so real error will be higher.

**It gets adults wrong, and last value should be used for them.** Over 18 at the origin, last
value scores 0.64 and cohort velocity 0.91, with a bias of +0.40 cm. The learned velocity
curve is still slightly positive past 18, where there are few players to learn from, so the
model has adults still growing a little. Any forecast shown for an adult
should be a flat line.

**Late bloomers are harder, as they should be.** MAE 1.20 on the planted late bloomers
against 0.86 overall, still about a third of the 3.39 that last value scores on them. Their spurt comes later than
the cohort's, which is the same fact the late-bloomer detector is built on.

**Age fraud makes the forecast run slightly tall, but only slightly.** On the planted
age-misrepresentation cases cohort velocity has a bias of +0.21 cm, against -0.04 for everyone.
The model expects growth for the stated age that the older body has already done. When football
included girls this bias was +0.91 cm and looked like a usable fraud signal; with boys-only
football it is too small to use on its own.

**It is much less accurate for girls**: MAE 2.26 cm with a bias of -1.34 (it runs short),
against 0.80 for boys. Girls now play table tennis only, about a dozen per dataset, so their
growth curve is learned from very few children. It still beats last value for girls (2.74),
but not by much. This is the price of a small population, and it is why the profile learns
the uncertainty band separately for each gender (below).

**On the player profile.** The profile drew cohort velocity until the XGBoost challenger
beat it; it now draws XGBoost for under-18s. See "On the player profile" under Challenger
models below. From 18 it still draws a flat line at the last reading, because of the adult
defect above.

## Challenger models

The thesis proposes two machine-learning methods: gradient-boosted forecasting (XGBoost) and
isolation-forest anomaly detection. The v1 models above are transparent rules and curves that
already beat the graded baselines. `ml/challengers/` puts the two proposed methods through the
**same** evaluation, on the same seeds, with every setting fixed before the first run, so the
question "does the more complex model earn its place?" is answered with numbers.

```bash
python -m ml.run_forecast_eval --seed-sweep 20260827 7 99 404 555      # includes XGBoost
python -m ml.run_eval --seed-sweep 20260827 7 99 404 555 $(seq 1000 1014)  # includes the forest
```

The isolation forest needs scikit-learn (`ml/requirements.txt`); XGBoost is pinned in
`apps/api/requirements.txt`, because the profile now runs it. Without them the harness runs
the v1 models alone and says the challengers were skipped.

### Height forecast: XGBoost wins, mostly on the hard cases

XGBoost learns the change in height from eight numbers known at the last reading, including
cohort velocity's own answer and the player's own recent growth rate, so it can learn when to
trust the child over the cohort. It trains inside each walk-forward snapshot, and the same
no-lookahead test that guards the v1 models passes for it (`test_challengers.py`).

MAE in cm, mean of five seeds, same cases for every model:

| group | XGBoost | cohort velocity | last value |
| --- | --- | --- | --- |
| **under 18 (headline)** | **0.80** | 0.86 | 3.19 |
| boys under 18 | 0.78 | 0.80 | 3.21 |
| girls under 18 | **1.25** | 2.26 | 2.74 |
| planted late bloomers | **1.04** | 1.20 | 3.39 |
| 6 to 12 months ahead | 0.94 | 1.02 | 4.63 |
| 18 and over | 0.68 | 0.91 | **0.64** |

It wins on all five seeds (0.85, 0.80, 0.77, 0.78, 0.81 against 0.87, 0.86, 0.88, 0.82, 0.88),
though the per-seed 95% intervals overlap. Read it this way:

- **For boys it is barely different** (0.78 against 0.80). On the smooth growth the generator
  makes, cohort velocity is already close to the 0.62 cm noise floor, and there is little left
  to learn.
- **The gain is on the hard cases.** Girls: 1.25 against 2.26, because XGBoost learns from
  boys and girls together with gender as one input, instead of a girls-only curve from a dozen
  children. Late bloomers: 1.04 against 1.20, because it can follow the child's own late spurt.
- **It mostly fixes the adult defect** (0.68 against cohort velocity's 0.91, bias +0.07
  against +0.40), but last value is still the best model for adults.
- **Age fraud:** its bias on planted cases is +0.41 against +0.21, a slightly stronger version
  of the "runs tall" signal noted above, still small.

**Its band holds, per gender.** The profile learns its 80% band for each gender separately,
from earlier forecasts whose outcome was already measured. Checked that way (walk-forward,
under 18, pooled over the five datasets; printed at the end of the sweep):

| band around | boys: inside | boys: width | girls: inside | girls: width |
| --- | --- | --- | --- | --- |
| cohort velocity | 81.0% of 12,550 | 2.55 cm | 73.0% of 126 | 4.69 cm |
| **XGBoost** | **80.2%** of 11,197 | **2.46 cm** | **77.4%** of 106 | **2.82 cm** |

For boys both are close to the nominal 80%, XGBoost's a little closer and a little narrower.
For girls XGBoost's band is 40% narrower and closer to nominal, though a hundred checks is a
small sample and both undercover. XGBoost has fewer checks because it declines at the earliest
origins, when there are too few readings to train on (fewer than 200 pairs).

**On the player profile.** The API runs this same code, not a copy
(`apps/api/app/services/forecast.py`), on the rows in its own database. Under 18 it draws
XGBoost 3, 6 and 12 months ahead; from 18 a flat line at the last reading, because last value
is still the best model for adults. The band comes from XGBoost's own past errors on that
database, per horizon and per gender, and the profile states how many past readings for that
gender fell inside it. On the local synthetic dataset: 81% for boys (2,130 of 2,637), 81% for
girls (42 of 52). It draws nothing, and says why, when a player has fewer than two readings,
no date of birth or gender, a last reading more than a year old, or fewer than 30 past
forecasts for their age group and gender in a horizon (adult girls, on the synthetic data).
`apps/api/tests/test_forecast.py` checks that the profile's number equals the evaluated
forecaster's, and `ml/tests/test_challengers.py` that it trains without scikit-learn, which
the API image does not have.

The model takes about nine seconds to build inside the API container (a walk-forward run with
an XGBoost fit at every origin). The API builds it in the background when it starts and
rebuilds it in the background every five minutes, so a profile does not wait for it. A
player's own readings are read fresh on every request, so a height a coach has just logged
moves that player's forecast at once.

### Age misrepresentation: isolation forest ties, and the rule stays

The forest is fitted on growth features of the same eligible players as the rule, with no
labels and no prevalence given to it (`contamination="auto"`), and it flags only anomalies in
the direction age fraud points: big for the stated age and no longer growing. An isolation
forest also isolates small, fast-growing children, who are late bloomers, and calling them
frauds is the worst mistake this platform could make; `test_challengers.py` guards it.

Counts pooled over 20 seeds, same 180 planted cases for both:

| | caught | false accusations | precision | recall | F1 |
| --- | --- | --- | --- | --- | --- |
| rule (v1) | 92 | **57** | **0.617** | 0.511 | 0.559 |
| isolation forest | **112** | 102 | 0.523 | **0.622** | 0.569 |

The F1 scores are a tie. The forest catches 20 more cases at the cost of 45 more false
accusations. For a flag that accuses a child of lying about their age, a false accusation costs
more than a miss, so **the rule stays**. The forest shows no relative age bias either (false
positive rate 2.0% to 2.9% across quarters, p = 0.61).

### What this says

Neither method was a wasted experiment, and neither is a free win. The more complex forecaster
earns its place where the simple one is known to struggle (few children to learn from, late
spurts), and the unsupervised detector does not beat a well-reasoned rule on the metric that
matters for an accusation. That matches the literature review's conclusion that evaluation
design, not model complexity, is the constraint.

## Relative age audit

Children born early in the selection year are older, bigger and more mature than team-mates
born late in it, and youth selection follows that advantage (Cobley et al. 2009). The most
recent review of machine learning for talent identification asks that every model be audited
by birth quarter (Tang et al. 2026). Both evaluations now do it, with no extra command:

```bash
python -m ml.run_eval --seed-sweep 20260827 7 99 404 555 $(seq 1000 1014)
python -m ml.run_forecast_eval --seed-sweep 20260827 7 99 404 555
```

Birth quarter is the calendar quarter of the **stated** date of birth, because age groups run
on the calendar year (the cutoff FIFA youth competitions use) and the stated date is all a
deployment has. The code is `evaluation/fairness.py`.

**What is measured.** For each detector, per quarter: recall, and the false positive rate
among players who are not positive, which is the fairness question that matters (is a child
without the condition more likely to be flagged because of when they were born?). A
chi-square test on the false positives says whether the rate differs by quarter. A sweep adds
the confusion counts over all datasets before testing, rather than averaging rates.

**It needs 20 datasets, not 5.** A dataset flags about 14 players, so one seed has only a
handful of false positives per quarter and five seeds are not enough to see even a real bias.
The harness carries a control that is biased on purpose, `baselines.shortest_for_birth_year`,
which compares each child with everyone born in the same calendar year, the textbook source
of the relative age effect. Over 5 seeds it flags nearly three times as many Q4 children as Q1
(19 against 7) and the test still says p = 0.41. Over 20 seeds it is caught decisively. That control is how the
audit's "no difference" verdicts earn trust: they mean something only while the control is
still caught.

**Results, false positive rate by birth quarter, counts pooled over 20 datasets:**

| detector | Q1 Jan-Mar (oldest) | Q2 | Q3 | Q4 Oct-Dec (youngest) | chi-square, p |
| --- | --- | --- | --- | --- | --- |
| late_bloomer v1 | 0.9% | 2.3% | 2.0% | 1.6% | 5.94, p = 0.12 |
| baseline: shortest for age | 4.9% | 6.4% | 4.4% | 5.4% | 4.28, p = 0.23 |
| fraud: age misrepresentation | 1.8% | 1.5% | 1.7% | 0.8% | 3.99, p = 0.26 |
| duplicate v1 | 0.0% | 0.0% | 0.0% | 0.0% | 0.00, p = 1.0 |
| **control: birth-year cohort** | **0.5%** | **1.3%** | **2.4%** | **3.1%** | **21.20, p < 0.001** |

No detector shows a detectable difference by quarter, and the biased control does. The
late-bloomer detector is the closest call (p = 0.12), but its pattern is not the relative age
one: Q1 is flagged least, and Q2, not Q4, most. The reason it stays clean is a design choice
made for other reasons: its height reference is bucketed by exact age at each measurement
(`features.height_z`), not by birth year, so a December child is compared with children of the
same age rather than with older team-mates.

**Forecasts by quarter.** Cohort velocity MAE, under 18 at origin, mean of five seeds: Q1
0.80 cm, Q2 0.88, Q3 0.90, Q4 0.86, with a bias within 0.1 cm of zero in every quarter. The
oldest quarter is forecast slightly best, but the youngest is not the worst, and the gaps are
smaller than the seed to seed spread, so there is no relative age pattern to report.

**What this cannot say.** The generator draws birth dates uniformly, so the synthetic
population has no relative age effect of its own. That is what makes this a clean test of the
models: any difference between quarters would come from them, not from the data. It does not
show how they would behave on a real academy, where Q1 children are over-represented and a
detector trained on past selection decisions could learn the bias. Recall by quarter is also
too noisy to test (positives per quarter are small even pooled), so only the false positive
rate is tested. Maturation, the other half of that review's recommendation, is audited only
through the planted late bloomers until the maturity-offset spike lands.

## The late-bloomer backtest

```bash
python -m ml.run_backtest --seed-sweep 20260827 7 99 404 555
python -m ml.run_backtest --seed-sweep 20260827 7 99 404 555 --players 1000
python -m ml.run_backtest --seed-sweep 20260827 7 99 404 555 --players 1000 --attrition
```

The question the project exists to answer: when an academy would have released a late bloomer
for being small, would the system have flagged them? The backtest goes back to past dates,
gives the detector only the data that existed on each one, and finds each player's **decision
moment**, the first date on which they fall in the **size cut**: the shortest quarter of their
sex among players aged 12 to 16 and measured in the last six months. The size cut stands in
for current practice. `ml/backtest.py` has the full definition, and every constant in it was
fixed before the first run.

**Result**, pooled over the five reported seeds at 1000 players each (the larger population
gives tighter intervals; the default 212 is in brackets):

| at the moment of the size cut | flagged |
| --- | --- |
| late bloomers the system had measured 3+ times | **47%**, 40 of 86, CI 36 to 57% (65%, 13 of 20) |
| other small players measured 3+ times | **16%**, 23 of 142, CI 11 to 23% (14%, 5 of 36) |
| late bloomers measured fewer than 3 times | **0%**, 0 of 117 (0 of 24) |

So the sentence the project can defend is:

> Of the late bloomers a size-based cut would have released, the system flagged about half of
> those it had measured at least three times, against about one in six of the other small
> players. It could not flag any it had measured fewer than three times, and that was more
> than half of them.

Before the boys-only change the other small players were flagged at 10% ("one in ten"); on
boys-only football it is 16%. The detection rate for late bloomers held (46% then, 47% now).

The last clause is the main practical finding. The detector needs a growth rate, and a growth
rate needs history, so **a player who is measured once on arrival and cut a few months later
cannot be helped by any model**. The fix is operational rather than statistical: measure every
player at intake and every few months after. The coach logging screen exists for that.

The two sizes disagree more than their intervals suggest they should (47% against 65%). The
detector's thresholds were tuned on 212-player datasets, where the cohort reference is built
from fewer children, and they transfer imperfectly to a larger population. Reported rather than
retuned; the larger figure is the one to quote.

### What this means for a backtest on real data

A real dataset has no answer key. The backtest then scores against what can be observed:
a player **caught up** if, a year or more after the cut, they sit at least 0.5 standard
deviations higher relative to their age group. On synthetic data the report checks that label
against the planted truth, and it fails:

| 'caught up' vs the planted truth, 1000 players x 5 | |
| --- | --- |
| median follow-up from the cut | 1.8 years |
| late bloomers the label finds | 9%, 15 of 176 |
| players the label finds who are late bloomers | 33%, 15 of 46 |

After under two years most late bloomers have not caught up yet, so the label misses most of
them, and every rate built on it describes the label rather than the system. The report prints
a warning when this happens. **A real-data backtest needs several years of follow-up**, which
means historical records going back four or five years, before its catch-up numbers mean
anything. The detection side (who was flagged at the cut) needs only the records up to the cut.

### Players who disappear

In real data the players released after a cut stop being measured, so they have no outcome,
and they are not a random sample. `--attrition` plants that effect: at the age-14 review, the
smaller a football player is for their age, the likelier they are to be released, and their
later rows are removed. At 1000 players x 5:

| | as generated | with release at 14 |
| --- | --- | --- |
| small players with an outcome | 88% | 74% |
| late bloomer recall, scored on everyone | 20% | 20% |
| late bloomer recall, scored on stayers only | 20% | 20% |
| players observed to catch up | 46 | 38 |

The effect we expected, a backtest on the stayers overstating recall, **did not appear**:
released late bloomers were flagged at about the same rate as the ones who stayed, so dropping
them left the rate where it was. What release did do is cost about one in eight of the evaluable
players (427 down to 372) and about a sixth of the observed success stories (46 down to 38). On real data, that is the
risk to plan for: fewer cases than the cohort size suggests, and the catch-ups that would make
the strongest case are disproportionately the ones missing. The report always prints how many
players have no outcome and how they compare with the rest.

### Running it on real data

```bash
python -m ml.export_db --out out/db_export     # refuses any path git would track
python -m ml.run_backtest --data-dir out/db_export
```

`export_db` writes the local database in the same format the generator does. It refuses to write
anywhere inside the repository that git would track, because on a machine with real data the
export is real data about children. Commit the numbers from the report, never the export.

## What the detectors actually do

All three are threshold rules over a handful of features, not trained models. That is a
deliberate v1: it is a floor for a real model to beat, it runs in milliseconds, and every
flag it raises comes with a sentence a coach can read, which the player profile screen
requires anyway.

- `detectors/features.py` builds per-player features from the JSON export. The two that do
  the work are `height_z`, how far a player sits from the median height for their **stated**
  age, and `maturity_mismatch`, which is `height_z - velocity_z`. Stated age throughout,
  because age fraud is a lie about the date of birth and using a true age, which a real
  deployment would not have, erases the thing being detected.
- `detectors/late_bloomer.py` flags adolescents who are below the cohort median and still
  growing fast. Height alone flags every short child in the academy; the pair is what
  separates a late maturer from a player who is simply short.
- `detectors/fraud.py` runs two independent rules, the arithmetic one and the maturity one.
- `detectors/duplicate.py` blocks candidates on sex, sport and birth year, then matches on
  Arabic-normalised name containment plus a date-of-birth relation. It deliberately never
  reads `status` or `merged_into`.
- `detectors/baselines.py` is what every score is printed next to.

## Known limits

- **Age fraud is missed below a stated age of 13.** Recall by stated age, over the 45 planted
  age-fraud cases in the five reported seeds:

  | stated age | 11 to 13 | 13 to 15 | 15 to 17 | 17+ |
  | --- | --- | --- | --- | --- |
  | recall | **0.07 (1/14)** | **0.76 (16/21)** | 1.00 (4/4) | 0.67 (4/6) |

  The signal is a body further through maturity than the record allows. A boy claiming 11 to
  13 who is really two years older is only just starting his growth spurt, so his body does
  not yet contradict the record. When football included girls, who spurt about two years
  earlier, this band scored 0.50; with boys-only football it catches almost nothing. The older
  bands have too few cases (10 in all) to say much. Worth knowing before anyone claims this
  covers the youth tier: it starts at about 13.
- **The cohort reference is built from the dataset itself**, planted cases included. At
  roughly 7% prevalence and using medians the effect is small, and it is the same problem
  any real deployment has, but it is not nothing.
- **Nothing here uses performance data for age fraud yet.** The generator plants
  `performance_outlier_for_stated_age` as a signal and the detector ignores it. That is the
  most obvious next improvement.
- **Girls are few, so everything learned about girls is thin.** Girls play table tennis only,
  about 5% of players. Cohort references and growth curves are per gender, so the girls' ones
  come from about a dozen children per dataset: forecast error is 2.26 cm for girls against
  0.80 for boys. Detector scores are not reported split by gender, and with this few girls a
  split would be mostly noise.

## Layout

```
detectors/     late-bloomer, fraud, duplicate + the features they share   done
evaluation/    metrics, the scoring harness, the relative age audit       done
challengers/   XGBoost forecaster and isolation forest, scored against v1  done
run_eval.py    CLI entry point                                            done
write_flags.py detector run that writes flags to the database             done
forecasting/   height forecasters + walk-forward harness                 done
backtest.py    the late-bloomer backtest, run_backtest.py is its CLI      done
export_db.py   database to JSON export, for running any harness on real data  done
similarity/    embedding + nearest-neighbor search                        TODO
assistant/     Ollama prompt + retrieval grounding                        TODO
artifacts/     trained models (gitignored)
```

`evaluation/` sits outside `detectors/` because the forecasting deliverable needs the same
scoring scaffolding with MAE and RMSE in place of precision and recall.

Model artifacts are gitignored (see repo `.gitignore`). Do not commit large binaries.
