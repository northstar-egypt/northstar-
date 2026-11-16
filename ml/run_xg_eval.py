"""Train and grade NorthStar's own expected-goals model on StatsBomb's open data.

    python -m ml.run_xg_eval --data-dir D:/northstar-data/statsbomb --cache D:/northstar-data/xg_shots.json

Trained on the non-penalty shots of the complete 2015/16 Premier League, La Liga, Serie A and
Ligue 1; settings chosen by grouped cross-validation on those alone. Scored once on shots it
never saw: the 2018 and 2022 World Cups and the 2023 African Cup of Nations, against StatsBomb's
own xG for the same shots. The data folder and the cache are outside the repository (real
players, decision 0008); the numbers this prints are in ml/README.md, "Expected goals".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from ml.xg import data, model


def _row(name: str, s: dict) -> str:
    return (f"  {name:<22} {s['log_loss']:.4f}   {s['brier']:.4f}   {s['auc']:.3f}   {s['calibration']:.4f}"
            f"   {s['xg_total']:7.1f} xG vs {s['goals']} goals")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--cache", type=Path, default=None)
    args = parser.parse_args()

    train, test = data.load(args.data_dir, args.cache)
    print(f"train: {len(train)} non-penalty shots, {sum(r['goal'] for r in train)} goals, "
          f"{len({r['match'] for r in train})} matches")
    print(f"test:  {len(test)} non-penalty shots, {sum(r['goal'] for r in test)} goals, "
          f"{len({r['match'] for r in test})} matches (held out)\n")

    fitted, chosen = {}, {}
    print("Settings, by grouped 5-fold cross-validation on the training leagues (log loss):")
    for kind in ("baseline", "logistic", "boosted"):
        best, cv = model.choose(kind, train)
        chosen[kind] = best
        for setting, loss in cv.items():
            mark = "  <- chosen" if setting == str(best) else ""
            print(f"  {kind:<9} {setting:<60} {loss:.4f}{mark}")
        fitted[kind] = model.fit(kind, best, train)

    y = np.array([r["goal"] for r in test])
    preds = {k: m.predict_proba(model.matrix(test, k))[:, 1] for k, m in fitted.items()}
    preds["StatsBomb xG"] = np.array([r["statsbomb_xg"] for r in test])
    print("\nHeld-out tournaments, every shot together:")
    print("  model                  log loss  Brier    AUC     calib.   total")
    for name, p in preds.items():
        print(_row(name, model.scores(y, p)))

    print("\nBy tournament (log loss; AUC):")
    for comp in dict.fromkeys(r["competition"] for r in test):
        idx = np.array([i for i, r in enumerate(test) if r["competition"] == comp])
        parts = ", ".join(f"{n} {model.scores(y[idx], p[idx])['log_loss']:.4f}; {model.scores(y[idx], p[idx])['auc']:.3f}"
                          for n, p in preds.items())
        print(f"  {comp} ({len(idx)} shots): {parts}")

    print("\nLog loss difference, 95% interval from resampling whole matches (negative = first is better):")
    for a, b in (("logistic", "baseline"), ("boosted", "baseline"), ("boosted", "logistic"),
                 ("boosted", "StatsBomb xG"), ("logistic", "StatsBomb xG")):
        mean, low, high = model.bootstrap_difference(test, preds[a], preds[b])
        print(f"  {a} - {b}: {mean:+.4f} ({low:+.4f} to {high:+.4f})")


if __name__ == "__main__":
    main()
