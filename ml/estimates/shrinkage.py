"""Rates shrunk towards the peer group by how much evidence there is (empirical Bayes).

A rate per 90 minutes from a short spell is mostly noise: one goal in 180 minutes is 0.5 per
90, a striker's rate, from a defender who scored once. The screens used to deal with that by a
cut-off (450 minutes) that throws evidence away and then trusts everything above it equally.
Here every player keeps their evidence and is pulled towards their peers by an amount that
shrinks as the evidence grows.

The model (gamma-Poisson, the standard one for counts over exposure):

- a player's true rate per 90 is drawn from the peer group's spread of rates, a gamma
  distribution with mean `mean` and strength `k`;
- their count over `exposure` 90-minute units is Poisson around rate times exposure.

Then the estimate after seeing `count` in `exposure` is

    (count + k * mean) / (exposure + k)

so `k` reads as matches: after k full matches of their own, a player's record and the peer
average count equally. `k` is fitted per group from how much more the players' rates spread
than chance alone would make them (the negative binomial likelihood), not chosen by hand.

Every estimate has an interval (the gamma posterior), and a next-season count has a predictive
interval (negative binomial), so a screen can say how sure it is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy import stats

# Bounds of the search for the gamma shape. At the top, the players' rates spread no more than
# chance makes them, and the estimate is the peer mean for everyone.
_LOG_SHAPE_RANGE = (-8.0, 14.0)
NO_SPREAD = math.exp(_LOG_SHAPE_RANGE[1])


@dataclass(frozen=True)
class Prior:
    """A peer group's spread of true rates per 90."""

    mean: float
    # Strength, in 90-minute units: how many full matches of a player's own record weigh as
    # much as the group average.
    k: float
    players: int

    @property
    def shape(self) -> float:
        return self.k * self.mean


@dataclass(frozen=True)
class Estimate:
    raw: float | None  # count / exposure, None with no exposure
    rate: float        # the shrunk estimate, per 90
    low: float         # the interval around it
    high: float
    weight: float      # how much of the estimate is the player's own record, 0 to 1


def _loglik(shape: float, mean: float, counts: list[int], exposures: list[float]) -> float:
    """Negative binomial log likelihood: the counts, with each rate drawn from gamma(shape, mean)."""
    k = shape / mean
    total = 0.0
    for y, e in zip(counts, exposures):
        total += (math.lgamma(y + shape) - math.lgamma(shape) - math.lgamma(y + 1)
                  + shape * math.log(k / (k + e)) + y * math.log(e / (k + e)))
    return total


def fit_prior(counts: list[int], exposures: list[float], min_exposure: float = 1.0) -> Prior:
    """Fit a group's prior from its players' counts and exposures (90-minute units).

    Only players with at least `min_exposure` take part in the fit. The mean is the pooled
    rate; the strength is the maximum-likelihood one, found by golden-section search on the
    log shape. Raises ValueError for a group with no exposure."""
    pairs = [(int(y), float(e)) for y, e in zip(counts, exposures) if e >= min_exposure]
    if not pairs:
        raise ValueError("no player with enough exposure to fit a prior")
    ys = [y for y, _ in pairs]
    es = [e for _, e in pairs]
    mean = sum(ys) / sum(es)
    if mean == 0:
        # Nobody in the group did it at all: every estimate is 0, as sure as the evidence allows.
        return Prior(mean=0.0, k=NO_SPREAD, players=len(pairs))

    lo, hi = _LOG_SHAPE_RANGE
    ratio = (math.sqrt(5) - 1) / 2
    a, b = hi - ratio * (hi - lo), lo + ratio * (hi - lo)
    fa, fb = _loglik(math.exp(a), mean, ys, es), _loglik(math.exp(b), mean, ys, es)
    for _ in range(80):
        if fa < fb:
            lo, a, fa = a, b, fb
            b = lo + ratio * (hi - lo)
            fb = _loglik(math.exp(b), mean, ys, es)
        else:
            hi, b, fb = b, a, fa
            a = hi - ratio * (hi - lo)
            fa = _loglik(math.exp(a), mean, ys, es)
    shape = math.exp((lo + hi) / 2)
    return Prior(mean=mean, k=shape / mean, players=len(pairs))


def estimate(count: int, exposure: float, prior: Prior, level: float = 0.8) -> Estimate:
    """The shrunk rate per 90 and its `level` interval, for `count` in `exposure` 90-minute units."""
    shape, k = prior.shape + count, prior.k + exposure
    rate = shape / k
    if prior.mean == 0 and count == 0:
        low = high = 0.0
    else:
        tail = (1 - level) / 2
        low = float(stats.gamma.ppf(tail, shape, scale=1 / k))
        high = float(stats.gamma.ppf(1 - tail, shape, scale=1 / k))
    return Estimate(raw=count / exposure if exposure > 0 else None, rate=rate, low=low, high=high,
                    weight=exposure / (exposure + prior.k))


def predictive_interval(count: int, exposure: float, prior: Prior, next_exposure: float,
                        level: float = 0.8) -> tuple[int, int]:
    """Where a count over `next_exposure` should fall, if the true rate does not change.

    Negative binomial: the gamma posterior mixed with Poisson noise over the new exposure."""
    shape, k = prior.shape + count, prior.k + exposure
    if shape == 0:
        return 0, 0
    p = k / (k + next_exposure)
    tail = (1 - level) / 2
    return int(stats.nbinom.ppf(tail, shape, p)), int(stats.nbinom.ppf(1 - tail, shape, p))


def predictive_coverage(count: int, exposure: float, prior: Prior, next_exposure: float,
                        low: int, high: int) -> float:
    """The chance, under the model, that the next count lands in [low, high]. Counts are whole
    numbers, so an "80%" interval usually holds more than 80%; this is what it should hold."""
    shape, k = prior.shape + count, prior.k + exposure
    if shape == 0:
        return 1.0
    p = k / (k + next_exposure)
    below = float(stats.nbinom.cdf(low - 1, shape, p)) if low > 0 else 0.0
    return float(stats.nbinom.cdf(high, shape, p)) - below


def percentile_of(value: float, peers: list[float]) -> int | None:
    """Where `value` sits among `peers`, 1 to 99, ties counted half: the same rule as every
    percentile in the app. None with no peers."""
    if not peers:
        return None
    below = sum(1 for p in peers if p < value)
    equal = sum(1 for p in peers if p == value)
    return max(1, min(99, round(100 * (below + equal / 2) / len(peers))))


def percentile_range(est: Estimate, peers: list[float]) -> tuple[int, int] | None:
    """The player's percentile among `peers`' estimates, as a range from the interval's two ends.
    None with no peers."""
    if not peers:
        return None
    return percentile_of(est.low, peers), percentile_of(est.high, peers)
