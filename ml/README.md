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
  population-average). A model that cannot beat those baselines is not done. Not started.
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
forecasting/   trajectory models + walk-forward harness                   TODO
similarity/    embedding + nearest-neighbor search                        TODO
assistant/     Ollama prompt + retrieval grounding                        TODO
artifacts/     trained models (gitignored)
```

`evaluation/` sits outside `detectors/` because the forecasting deliverable needs the same
scoring scaffolding with MAE and RMSE in place of precision and recall.

Model artifacts are gitignored (see repo `.gitignore`). Do not commit large binaries.
