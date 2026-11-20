"""Grade the talent estimates (ml/estimates) on real professional seasons.

    python -m ml.run_estimate_eval --cache-dir D:/northstar-data/footystats

The question: from one season, which predicts a player's next season best, their raw rate
per 90, their peer group's average, or the estimate that weighs the two by how much of the
player has been seen? Measured on non-penalty goals and assists per 90, for outfield players
in consecutive Premier League seasons (FootyStats, the test key's 2018/19 to 2024/25).

- Each season's priors are fitted on that season alone, per position group; nothing from the
  next season is used to make a prediction.
- The target is next season's rate, for players with NEXT_MINUTES or more next season, so
  the target itself is not mostly noise. This season can be any length from 90 minutes.
- Reported: mean absolute error, and the Poisson deviance of next season's counts (a proper
  score for counts, lower is better), per minutes band this season; and how often next
  season's count lands inside the 80% predictive interval, beside how often the model itself
  expects it to. Counts are whole numbers, so an interval cannot hold exactly 80%: the fair
  check is seen against expected, not seen against 80%.
- The headline is the two latest pairs (2022/23 to 2023/24, 2023/24 to 2024/25); the earlier
  pairs are printed too. No setting was tuned on either: the method has none to tune.

The cache is outside the repository (real players); the numbers are in ml/README.md,
"Talent estimates".
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

from ml.estimates import footystats, shrinkage

LEAGUE = "England Premier League"
MEASURES = ("np_goals", "assists")
OUTFIELD = ("defender", "midfielder", "forward")
NEXT_MINUTES = 900
BANDS = [("under 900", 90, 900), ("900 to 1,800", 900, 1800), ("over 1,800", 1800, 10_000)]
REPORTED_FROM = 2022  # pairs whose first season starts in 2022 or later are the headline


def _deviance(y: int, mu: float) -> float:
    mu = max(mu, 1e-9)
    return 2 * ((y * math.log(y / mu) if y > 0 else 0.0) - (y - mu))


def pairs(seasons: list[footystats.PlayerSeason]):
    """(this season, next season) for every player in two consecutive seasons."""
    by_year = defaultdict(dict)
    for s in seasons:
        by_year[s.start_year][s.player_id] = s
    for year in sorted(by_year):
        nxt = by_year.get(year + 1)
        if not nxt:
            continue
        for pid, s in by_year[year].items():
            if pid in nxt:
                yield s, nxt[pid]


def priors(seasons: list[footystats.PlayerSeason]) -> dict:
    """(start year, group, measure) -> Prior, fitted on that season's players of the group."""
    groups = defaultdict(list)
    for s in seasons:
        groups[(s.start_year, s.group)].append(s)
    out = {}
    for (year, group), rows in groups.items():
        for m in MEASURES:
            out[(year, group, m)] = shrinkage.fit_prior([getattr(r, m) for r in rows], [r.exposure for r in rows])
    return out


def evaluate(seasons: list[footystats.PlayerSeason], reported: bool) -> dict:
    fitted = priors(seasons)
    rows = defaultdict(lambda: defaultdict(list))
    for a, b in pairs(seasons):
        if a.group not in OUTFIELD or a.minutes < 90 or b.minutes < NEXT_MINUTES:
            continue
        if (a.start_year >= REPORTED_FROM) != reported:
            continue
        band = next(name for name, lo, hi in BANDS if lo <= a.minutes < hi)
        for m in MEASURES:
            prior = fitted[(a.start_year, a.group, m)]
            est = shrinkage.estimate(getattr(a, m), a.exposure, prior)
            target, y2 = getattr(b, m) / b.exposure, getattr(b, m)
            lo, hi = shrinkage.predictive_interval(getattr(a, m), a.exposure, prior, b.exposure)
            expected = shrinkage.predictive_coverage(getattr(a, m), a.exposure, prior, b.exposure, lo, hi)
            for key in (band, "all"):
                r = rows[m][key]
                r.append({
                    "raw": abs(est.raw - target), "peer": abs(prior.mean - target), "estimate": abs(est.rate - target),
                    "dev_raw": _deviance(y2, est.raw * b.exposure), "dev_peer": _deviance(y2, prior.mean * b.exposure),
                    "dev_estimate": _deviance(y2, est.rate * b.exposure), "inside": lo <= y2 <= hi,
                    "expected": expected,
                })
    return rows


def _mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def report(rows, title: str) -> None:
    print(f"\n{title}")
    for m in MEASURES:
        label = "non-penalty goals per 90" if m == "np_goals" else "assists per 90"
        print(f"\n  {label}")
        print("    this season's minutes   players   MAE: raw    peer   estimate | deviance: raw    peer   estimate"
              " | inside the interval: seen, model expects")
        for key in [b[0] for b in BANDS] + ["all"]:
            r = rows[m].get(key, [])
            if not r:
                continue
            print(f"    {key:<22} {len(r):>8}   {_mean([x['raw'] for x in r]):8.3f} {_mean([x['peer'] for x in r]):7.3f}"
                  f" {_mean([x['estimate'] for x in r]):9.3f} | {_mean([x['dev_raw'] for x in r]):12.3f}"
                  f" {_mean([x['dev_peer'] for x in r]):7.3f} {_mean([x['dev_estimate'] for x in r]):9.3f}"
                  f" | {_mean([x['inside'] for x in r]):9.1%}  {_mean([x['expected'] for x in r]):6.1%}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache-dir", required=True, type=Path)
    args = parser.parse_args()
    seasons = footystats.load(args.cache_dir, LEAGUE)
    print(f"{len(seasons)} player seasons with minutes, {LEAGUE}, "
          f"{min(s.season for s in seasons)} to {max(s.season for s in seasons)}")

    fitted = priors(seasons)
    print("\nFitted strength k (in full matches) per position group, median over seasons:")
    for m in MEASURES:
        for g in OUTFIELD:
            ks = sorted(p.k for (y, gg, mm), p in fitted.items() if gg == g and mm == m)
            means = sorted(p.mean for (y, gg, mm), p in fitted.items() if gg == g and mm == m)
            print(f"  {m:<9} {g:<11} k = {ks[len(ks) // 2]:6.1f}   peer rate = {means[len(means) // 2]:.3f} per 90")

    report(evaluate(seasons, reported=True), "REPORTED: pairs 2022/23 to 2023/24 and 2023/24 to 2024/25")
    report(evaluate(seasons, reported=False), "Earlier pairs, 2018/19 to 2022/23")


if __name__ == "__main__":
    main()
