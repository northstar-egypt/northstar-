# ML and intelligence

Owner: intelligence/ML workstream. Model code and, just as importantly, the evaluation
harnesses that prove the models hit the graded targets. Reads from the database, writes
results (forecasts, flags, similarity, embeddings) back to it.

## Scope

- **Forecasting** of player trajectories with uncertainty bands. Per-position age curves.
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

Five datasets, 212 players each. Headline F1 per detector:

| detector | 20260827 | 7 | 99 | 404 | 555 | mean | range |
| --- | --- | --- | --- | --- | --- | --- | --- |
| late_bloomer | 0.560 | 0.476 | 0.741 | 0.720 | 0.560 | **0.611** | 0.476 to 0.741 |
| fraud | 0.759 | 0.846 | 0.667 | 0.741 | 0.857 | **0.774** | 0.667 to 0.857 |
| duplicate | 1.000 | 1.000 | 1.000 | 0.909 | 1.000 | **0.982** | 0.909 to 1.000 |

Against the trivial baselines on the committed default seed, where flagging every player
scores F1 0.124 and random selection at the true prevalence scores 0.000 to 0.042.

Read those numbers with the following in mind.

**Thresholds were tuned on seeds 101, 202 and 303, and none of the five reported seeds is
one of them.** Tuning a threshold on the set you then report is the easiest way to publish
a number that does not survive contact with new data. The gap is visible: late-bloomer F1
averaged 0.658 on the calibration seeds and 0.611 on the reported ones.

**The spread is wide because the positive classes are small.** Fourteen late bloomers in
212 players means one case moving shifts recall by 7 points, and the 0.476 to 0.741 range
is mostly that. Every table the harness prints carries the raw TP/FP/FN counts and a Wilson
95% interval on recall, so nobody has to take a three-decimal F1 at face value.

**The duplicate score is high because the problem as generated is easy**, not because the
detector is clever. Clones always share sex and sport and sit within a few days of the
original's date of birth, so blocking plus normalised name matching finds nearly all of
them. The honest comparison is against the two controls in the same table: byte-identical
name matching gets recall 0.167, and reading the `merged_into` pointer, which is cheating
because it is the record of a merge a human already did, gets 0.500. Real duplicate
detection at national scale will be harder than this.

**The fraud headline mixes an easy problem with a hard one.** The harness splits them:

| fraud subtype | cases | F1 (default seed) |
| --- | --- | --- |
| implausible self-reported performance | 5 | 1.000 |
| age misrepresentation | 9 | 0.632 |

The perfect score on the first is arithmetic, not machine learning: those rows record more
goals than shots, more passes completed than attempted, and distances no human has run.
That check belongs in ingest validation rather than in a model, and the fact that it scores
perfectly is a statement about the generator. Age misrepresentation is the subtype that
matters, it carries 9 of the 14 cases, and at 0.632 it is doing about half the work the
headline 0.759 suggests. Anyone quoting the fraud number should quote this one alongside it.

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
| baseline: last value | 3.07 | 3.21 | 3.03 | 3.24 | 3.12 | 3.13 |
| baseline: population average | 5.39 | 5.57 | 5.36 | 5.74 | 5.02 | 5.42 |
| **cohort velocity** | 0.88 | 0.93 | 0.91 | 0.81 | 0.89 | **0.89** |
| centile tracking | 1.82 | 1.98 | 2.07 | 1.78 | 2.18 | 1.97 |

Cohort velocity is the last reading plus how much the median child of that sex grows between
the two ages, with the growth curve learned from the training window. It beats last value by
72% and population average by 84%, on every seed. RMSE and a player-resampled 95% interval on
MAE are in the full output.

**No constant was tuned against these numbers.** Every threshold in `forecasting/models.py`
was set before the first run and none has changed since. That is also why the adult defect
below is reported and not fixed.

**The uncertainty band** is the band the player profile needs. It is an 80% interval around
cohort velocity built from the errors of earlier forecasts whose outcomes had already been
measured by the origin, so it is walk-forward as well. Observed coverage on the five seeds:
81.6%, 82.0%, 80.9%, 82.8%, 84.3%, at a mean width of about 3 cm. Slightly wide, never
narrow.

Read the headline with these in mind.

**The problem as generated is smooth, so the model is close to the floor.** Synthetic heights
are a growth curve plus 0.55 cm of noise per reading. With that noise on both the last reading
and the target, a perfect forecaster still scores an MAE of about 0.62 cm. Cohort velocity
averages 0.70 up to three months ahead and 1.07 at six to twelve months. Real children are measured on
different stadiometers by different people and grow less tidily, so real error will be higher.

**It gets adults wrong, and last value should be used for them.** Over 18 at the origin, last
value scores 0.64 and cohort velocity 1.04, with a bias of +0.56 cm. The learned velocity
curve is still slightly positive past 18, where there are few players to learn from, so the
model has adults growing about half a centimetre a year. Any forecast shown for an adult
should be a flat line.

**Late bloomers are harder, as they should be.** MAE 1.12 on the 14 planted late bloomers
against 0.89 overall, still a third of the best baseline's 3.32. Their spurt comes later than
the cohort's, which is the same fact the late-bloomer detector is built on.

**Age fraud shows up as a forecast that runs tall.** On the planted age-misrepresentation
cases cohort velocity has a bias of +0.91 cm, against roughly zero for everyone else. The
model expects growth for the stated age that the older body has already done. A persistent
positive forecast residual is therefore a fraud signal the detector does not use yet.

**It is less accurate for girls**: 0.99 against 0.83 for boys. Girls are 34% of the
population and their reference curve is built from fewer children. The gap is smaller than
the gap to either baseline, but it is there and it is now measured.

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
| late bloomers the system had measured 3+ times | **46%**, 37 of 81, CI 35 to 56% (65%, 13 of 20) |
| other small players measured 3+ times | **10%**, 14 of 147, CI 6 to 15% (22%, 7 of 32) |
| late bloomers measured fewer than 3 times | **0%**, 0 of 110 (0 of 22) |

So the sentence the project can defend is:

> Of the late bloomers a size-based cut would have released, the system flagged about half of
> those it had measured at least three times, against one in ten of the other small players.
> It could not flag any it had measured fewer than three times, and that was more than half
> of them.

The last clause is the main practical finding. The detector needs a growth rate, and a growth
rate needs history, so **a player who is measured once on arrival and cut a few months later
cannot be helped by any model**. The fix is operational rather than statistical: measure every
player at intake and every few months after. The coach logging screen exists for that.

The two sizes disagree more than their intervals suggest they should (46% against 65%). The
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
| late bloomers the label finds | 22%, 37 of 171 |
| players the label finds who are late bloomers | 67%, 37 of 55 |

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
| small players with an outcome | 87% | 74% |
| late bloomer recall, scored on everyone | 19% | 19% |
| late bloomer recall, scored on stayers only | 20% | 20% |
| players observed to catch up | 55 | 35 |

The effect we expected, a backtest on the stayers overstating recall, **did not appear**:
released late bloomers were flagged at about the same rate as the ones who stayed, so dropping
them left the rate where it was. What release did do is cost about one in seven of the evaluable
players (416 down to 353) and more than a third of the observed success stories (55 down to 35). On real data, that is the
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

- **Age fraud only works in mid-adolescence.** Recall by stated age, over the 45 planted
  age-fraud cases in the five reported seeds:

  | stated age | 11 to 13 | 13 to 15 | 15 to 17 | 17+ |
  | --- | --- | --- | --- | --- |
  | recall | 0.50 (7/14) | **0.76 (16/21)** | 0.50 (2/4) | 0.50 (3/6) |

  The signal is a body further through maturity than the record allows, and it is only
  legible while the cohort is diverging. Before about 13 there is not enough spread between
  age groups for a two-year lie to stand out, and after about 16 everyone has stopped
  growing, so the velocity half of the signal goes flat. Worth knowing before anyone claims
  this covers the youth tier: it covers the middle of it.
- **The cohort reference is built from the dataset itself**, planted cases included. At
  roughly 7% prevalence and using medians the effect is small, and it is the same problem
  any real deployment has, but it is not nothing.
- **Nothing here uses performance data for age fraud yet.** The generator plants
  `performance_outlier_for_stated_age` as a signal and the detector ignores it. That is the
  most obvious next improvement.
- **`sex` is used for cohort bucketing** and the reference thins out for female players,
  who are 34% of the population. Scores are not currently reported split by sex. They
  should be before anyone claims this works for everyone.

## Layout

```
detectors/     late-bloomer, fraud, duplicate + the features they share   done
evaluation/    metrics and the scoring harness, shared with forecasting   done
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
