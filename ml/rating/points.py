"""Point rating: each player's strength, adjusted for opponents, read from every point played.

The challenger to Glicko-2 (ml/rating/glicko2.py). Glicko-2 sees a match as one bit, won or
lost. A table tennis match is about ninety points, and the share of them a player wins says
far more about them than the result does. On the tuning seeds plain point win rate ranked
players better than Glicko-2 did. This model keeps the points and still adjusts for who they
were against.

The model
---------
Each player has a strength theta. A point between players i and j goes to i with probability

    p = 1 / (1 + exp(-(theta_i - theta_j)))

which is the Bradley-Terry model, applied to points instead of matches. Every point in every
confirmed match between two registered players is evidence. Each theta has a normal prior
centred on 0 (an average registered player) with standard deviation `PRIOR_SD`, so a player
with three matches is pulled toward average instead of being declared the best in the
country. The fit is the most likely set of strengths given the points and the prior
(maximum a posteriori), found by Newton's method.

Uncertainty
-----------
The standard error of each theta comes from the curvature of the fit at its peak (the Laplace
approximation, the usual one for this kind of model). It shrinks as a player plays more
points against well-connected opponents and stays wide for a player who has barely played.

Reading it
----------
theta means little on its own, so what is shown is what it implies against an average
registered player of the same gender: the share of points the player would win, and from
that, the chance of winning a best-of-five match. Both come with a range from the standard
error.

Standard library only, like the rest of the v1 models.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from math import comb

from ml import sport_modules
from ml.rating.matches import Match, _as_date

# The prior's spread on theta. 0.15 means a typical player wins between about 46% and 54% of
# points against an average one. Chosen on the tuning seeds; see ml/README.md.
PRIOR_SD = 0.15
# A rating is shown only when the range of point share against an average player (two
# standard errors either side) is at most this wide: 7 points in 100. Chosen on the tuning
# seeds; it shows about nine players in ten and holds the truth for 98% of them.
SHOW_MAX_POINT_RANGE = 0.07
_ITERATIONS = 50
_TOLERANCE = 1e-9


@dataclass(frozen=True)
class PointMatch:
    """One confirmed match between registered players, as points won by each side."""

    a: str
    b: str
    points_a: int
    points_b: int


@dataclass(frozen=True)
class Strength:
    theta: float
    se: float
    matches: int

    def point_share(self, z: float = 0.0) -> float:
        """Share of points won against an average player, at `z` standard errors from the estimate."""
        return _logistic(self.theta + z * self.se)

    @property
    def point_range(self) -> tuple[float, float]:
        return self.point_share(-2.0), self.point_share(2.0)

    @property
    def shown(self) -> bool:
        low, high = self.point_range
        return high - low <= SHOW_MAX_POINT_RANGE

    def match_win(self, z: float = 0.0, best_of: int = 5) -> float:
        return match_probability(self.point_share(z), best_of)


def _logistic(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def set_probability(p: float) -> float:
    """Chance of winning a set to 11, win by two, when each point is won with probability p."""
    q = 1.0 - p
    # Reach 11 while the opponent has at most 9.
    before_deuce = sum(comb(10 + k, k) * p**11 * q**k for k in range(10))
    # From 10-10 on, someone has to go two clear.
    at_ten_all = comb(20, 10) * p**10 * q**10
    return before_deuce + at_ten_all * p * p / (p * p + q * q)


def match_probability(p: float, best_of: int = 5) -> float:
    """Chance of winning a best-of-n match, from the chance of winning a point."""
    s = set_probability(p)
    need = best_of // 2 + 1
    return sum(comb(need - 1 + k, k) * s**need * (1.0 - s) ** k for k in range(need))


def point_matches(matches: list[Match], rows_by_id: dict[str, dict]) -> list[PointMatch]:
    """The confirmed matches, with each side's points read from one of the match's rows."""
    out = []
    for m in matches:
        if not m.confirmed:
            continue
        row = rows_by_id[m.entry_ids[0]]
        player = str(row["player_id"])
        mine, theirs = row["metrics"]["points_won"], row["metrics"]["points_lost"]
        other = m.loser if player == m.winner else m.winner
        out.append(PointMatch(player, other, mine, theirs))
    return out


OUTSIDER = "outsider:"


def outsider_matches(rows: list[dict], group_of: dict[str, str], before=None) -> list[PointMatch]:
    """Matches against opponents who are not on the platform, against one stand-in per group.

    Nobody knows who an outsider was, so every outsider a player in a group (a gender) met is
    treated as one opponent, "the typical outsider" for that group, whose strength the fit
    learns like anyone else's. That keeps the evidence from those points without assuming
    outsiders are as good as registered players, and without linking the boys' and girls'
    scales through a shared stand-in. Same rule as for registered matches: a row that is only
    the player's own word (self-submitted) does not count.
    """
    out = []
    for r in rows:
        if r.get("opponent_player_id") or r.get("source") == "self_submitted":
            continue
        if before is not None and _as_date(r["period_start"]) >= before:
            continue
        if sport_modules.impossibilities(r["metrics"], r.get("schema_ref", "")):
            continue
        player = str(r["player_id"])
        m = r["metrics"]
        out.append(PointMatch(player, OUTSIDER + group_of.get(player, ""), m["points_won"], m["points_lost"]))
    return out


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting. The systems here are a few dozen wide."""
    n = len(vector)
    a = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(col + 1, n):
            factor = a[r][col] / a[col][col]
            if factor:
                for c in range(col, n + 1):
                    a[r][c] -= factor * a[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (a[r][n] - sum(a[r][c] * x[c] for c in range(r + 1, n))) / a[r][r]
    return x


def fit(matches: list[PointMatch], prior_sd: float = PRIOR_SD) -> dict[str, Strength]:
    """The most likely strengths given every point and the prior, with standard errors."""
    players = sorted({m.a for m in matches} | {m.b for m in matches})
    if not players:
        return {}
    index = {p: i for i, p in enumerate(players)}
    n = len(players)
    precision = 1.0 / (prior_sd * prior_sd)
    theta = [0.0] * n
    played = [0] * n
    for m in matches:
        played[index[m.a]] += 1
        played[index[m.b]] += 1

    def curvature() -> tuple[list[float], list[list[float]]]:
        # Gradient and negative Hessian of the log posterior.
        grad = [-precision * t for t in theta]
        info = [[0.0] * n for _ in range(n)]
        for i in range(n):
            info[i][i] = precision
        for m in matches:
            i, j = index[m.a], index[m.b]
            total = m.points_a + m.points_b
            p = _logistic(theta[i] - theta[j])
            g = m.points_a - total * p
            grad[i] += g
            grad[j] -= g
            w = total * p * (1.0 - p)
            info[i][i] += w
            info[j][j] += w
            info[i][j] -= w
            info[j][i] -= w
        return grad, info

    for _ in range(_ITERATIONS):
        grad, info = curvature()
        step = _solve(info, grad)
        theta = [t + s for t, s in zip(theta, step)]
        if max(abs(s) for s in step) < _TOLERANCE:
            break

    _, info = curvature()
    out = {}
    for p, i in index.items():
        unit = [0.0] * n
        unit[i] = 1.0
        variance = _solve(info, unit)[i]
        out[p] = Strength(theta[i], math.sqrt(max(variance, 0.0)), played[i])
    return out


def win_probability(a: Strength | None, b: Strength | None, best_of: int = 5) -> float:
    """The chance that `a` beats `b` in a best-of-n match. An unrated side counts as average."""
    ta = a.theta if a else 0.0
    tb = b.theta if b else 0.0
    return match_probability(_logistic(ta - tb), best_of)
