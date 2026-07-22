# ML and intelligence

Owner: intelligence/ML workstream. Model code and, just as importantly, the evaluation
harnesses that prove the models hit the graded targets. Reads from the database, writes
results (forecasts, flags, similarity, embeddings) back to it.

## Scope

- **Forecasting** of player trajectories with uncertainty bands. Per-position age curves.
- **Detectors**: late-bloomer, fraud, duplicate. Measured with precision / recall / F1
  against the **planted ground truth** in the synthetic dataset.
- **Sustainability flags**: xG vs actual for football.
- **Similarity**: player embeddings via sentence-transformers.
- **Anomaly detection**: crosses over with the security workstream (self-submission fraud).
- **LLM assistant**: grounded natural-language queries via a local Ollama model. It phrases
  what the data and models already know; it does not invent player data.

## Evaluation is a first-class deliverable

We are graded on measured performance, so every model ships with a harness:

- **Detectors**: precision / recall / F1 against planted ground truth.
- **Forecasts**: walk-forward validation, MAE / RMSE against two baselines (last-value and
  population-average). A model that cannot beat those baselines is not done.
- **Access control** and **system demo** targets live with their workstreams, not here.

## Layout (to grow)

```
forecasting/   trajectory models + walk-forward harness   (TODO)
detectors/     late-bloomer, fraud, duplicate + metrics    (TODO)
similarity/    embedding + nearest-neighbor search         (TODO)
assistant/     Ollama prompt + retrieval grounding         (TODO)
artifacts/     trained models (gitignored)
```

Model artifacts are gitignored (see repo `.gitignore`). Do not commit large binaries.
TODO: pin ML dependencies in a `requirements.txt` here, separate from the API image.
