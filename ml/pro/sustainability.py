"""Finishing against expected goals: is a player scoring more (or fewer) than their chances
were worth, and is that more than luck?

The question scouts ask of a hot striker is whether it will last. Expected goals (xG) say how
many goals the chances a player had would produce for an ordinary finisher. A gap between goals
and xG in one season is mostly chance: published work on real leagues finds that scoring above
xG one season predicts very little about the next (a correlation of about 0.1 to 0.2), and the
synthetic league is built to behave the same way (pro_league.py).

So a verdict here is only "above" or "below" when the gap is bigger than chance usually makes.
Goals are treated as a Poisson count with the player's non-penalty xG as its mean: the range is
the 10th to 90th percentile of goals an ordinary finisher with those chances scores. Penalties
are left out on both sides, since they are a different skill and a taker's xG is inflated by them.

Pooling seasons (`career`) is the honest way to say more: three seasons of chances make a range
narrow enough that a real finisher can stand out. ml/README.md, "Pro tier", measures both
against the true finishing planted in the synthetic league.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ml.pro.seasons import SeasonRow

# Below this many expected goals, the range is so wide that any verdict is noise.
MIN_NPXG = 2.0
LOW, HIGH = 0.10, 0.90


@dataclass(frozen=True)
class Finishing:
    np_goals: int
    npxg: float
    # The 10th to 90th percentile of non-penalty goals for an ordinary finisher with these chances.
    low: int | None
    high: int | None
    # "above", "below", "in line", or "too few chances".
    verdict: str
    seasons: int


def poisson_cdf(k: int, mean: float) -> float:
    if k < 0:
        return 0.0
    term = total = math.exp(-mean)
    for i in range(1, k + 1):
        term *= mean / i
        total += term
    return min(1.0, total)


def poisson_quantile(q: float, mean: float) -> int:
    k = 0
    while poisson_cdf(k, mean) < q:
        k += 1
    return k


def judge(np_goals: int, npxg: float, seasons: int = 1) -> Finishing:
    if npxg < MIN_NPXG:
        return Finishing(np_goals, round(npxg, 2), None, None, "too few chances", seasons)
    low, high = poisson_quantile(LOW, npxg), poisson_quantile(HIGH, npxg)
    verdict = "above" if np_goals > high else "below" if np_goals < low else "in line"
    return Finishing(np_goals, round(npxg, 2), low, high, verdict, seasons)


def season(row: SeasonRow) -> Finishing:
    return judge(row.np_goals, float(row.metrics["npxg"]))


def career(rows: list[SeasonRow]) -> Finishing:
    """Every season on record pooled: one range over all the chances."""
    return judge(sum(r.np_goals for r in rows), sum(float(r.metrics["npxg"]) for r in rows), len(rows))
