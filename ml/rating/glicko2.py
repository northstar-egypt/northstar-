"""Glicko-2: a rating per player, with a measured uncertainty, from who beat whom.

This is Mark Glickman's published algorithm ("Example of the Glicko-2 system", 2013), written
out step by step so it can be checked against the paper. The paper's own worked example is a
test (ml/tests/test_rating.py), so a slip in any formula fails loudly.

Why Glicko-2 rather than Elo: every rating carries a rating deviation (RD), the system's own
measure of how unsure it is. A player with four matches has a wide RD and the profile says
"not known yet" instead of showing a number with false confidence. Elo has no such quantity,
so the cut-off would be a match count picked by hand.

Ratings are on the familiar scale (start 1500, RD 350). Internally the paper works on a scale
divided by 173.7178; the conversion is at the edges of `update`.

Standard library only, like the rest of the v1 models in ml/.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

SCALE = 173.7178
START_RATING = 1500.0
START_RD = 350.0
START_VOLATILITY = 0.06
# How much a player's volatility may change between periods. The paper suggests 0.3 to 1.2.
TAU = 0.5
_EPSILON = 0.000001


@dataclass(frozen=True)
class Rating:
    rating: float = START_RATING
    rd: float = START_RD
    volatility: float = START_VOLATILITY

    @property
    def low(self) -> float:
        """The lower end of the range shown: about 95% if the model's assumptions hold."""
        return self.rating - 2 * self.rd

    @property
    def high(self) -> float:
        return self.rating + 2 * self.rd


@dataclass(frozen=True)
class Game:
    """One result from a player's point of view: the opponent as rated before the period."""

    opponent: Rating
    score: float  # 1 win, 0 loss (table tennis has no draws)


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi * math.pi))


def _expected(mu: float, mu_j: float, phi_j: float) -> float:
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def win_probability(a: Rating, b: Rating) -> float:
    """The chance that `a` beats `b`, allowing for the uncertainty in both ratings.

    Combining both deviations is the usual Glicko way to predict a single game: an unsure
    rating on either side pulls the prediction toward a coin flip.
    """
    mu_a, mu_b = (a.rating - START_RATING) / SCALE, (b.rating - START_RATING) / SCALE
    phi = math.sqrt(a.rd**2 + b.rd**2) / SCALE
    return 1.0 / (1.0 + math.exp(-_g(phi) * (mu_a - mu_b)))


def idle(r: Rating, periods: int = 1) -> Rating:
    """A player who played nothing: the rating stays, the uncertainty grows (step 6 of the paper)."""
    phi = r.rd / SCALE
    for _ in range(periods):
        phi = math.sqrt(phi * phi + r.volatility * r.volatility)
    return Rating(r.rating, min(phi * SCALE, START_RD), r.volatility)


def update(r: Rating, games: list[Game], tau: float = TAU) -> Rating:
    """One rating period for one player (steps 2 to 8 of the paper)."""
    if not games:
        return idle(r)

    mu = (r.rating - START_RATING) / SCALE
    phi = r.rd / SCALE
    sigma = r.volatility

    # Step 3 and 4: the estimated variance from these games, and the estimated improvement.
    v_inv = 0.0
    delta_sum = 0.0
    for game in games:
        mu_j = (game.opponent.rating - START_RATING) / SCALE
        phi_j = game.opponent.rd / SCALE
        g = _g(phi_j)
        e = _expected(mu, mu_j, phi_j)
        v_inv += g * g * e * (1.0 - e)
        delta_sum += g * (game.score - e)
    v = 1.0 / v_inv
    delta = v * delta_sum

    # Step 5: the new volatility, by the Illinois algorithm, as the paper gives it.
    a = math.log(sigma * sigma)

    def f(x: float) -> float:
        ex = math.exp(x)
        return (ex * (delta * delta - phi * phi - v - ex)) / (
            2.0 * (phi * phi + v + ex) ** 2
        ) - (x - a) / (tau * tau)

    big_a = a
    if delta * delta > phi * phi + v:
        big_b = math.log(delta * delta - phi * phi - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        big_b = a - k * tau
    f_a, f_b = f(big_a), f(big_b)
    while abs(big_b - big_a) > _EPSILON:
        big_c = big_a + (big_a - big_b) * f_a / (f_b - f_a)
        f_c = f(big_c)
        if f_c * f_b <= 0:
            big_a, f_a = big_b, f_b
        else:
            f_a /= 2.0
        big_b, f_b = big_c, f_c
    new_sigma = math.exp(big_a / 2.0)

    # Steps 6 to 8: the new deviation and rating, back on the familiar scale.
    phi_star = math.sqrt(phi * phi + new_sigma * new_sigma)
    new_phi = 1.0 / math.sqrt(1.0 / (phi_star * phi_star) + 1.0 / v)
    new_mu = mu + new_phi * new_phi * delta_sum
    return Rating(new_mu * SCALE + START_RATING, new_phi * SCALE, new_sigma)
