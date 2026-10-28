"""Split-half reliability for team gap analysis (decision 0003, "How it is checked").

There is no answer key for "the right signing", so gap analysis is not scored like a detector.
What can be measured is whether its numbers are stable enough to act on: compute every team and
player statistic from the first half of a season and from the second half, and see how well the
two agree. A statistic whose halves barely agree is mostly noise over a half season, and only a
little better over a whole one.

- **Team statistics**: the correlation, across the league's 18 teams, between a statistic's
  first-half and second-half values, and how often a team in the bottom third in one half is
  in the bottom third in the other (chance alone gives a third).
- **Player statistics**: for a minutes threshold T over a season, the players with T/2 or more
  in each half; the correlation of each statistic between the halves, within position group
  (each half standardised within the group, so the gap between a striker's and a centre back's
  numbers does not count as agreement). A season is two halves, so the Spearman-Brown formula
  2r / (1 + r) gives the reliability of the season's figure.

`gaps.MIN_MINUTES` is the smallest threshold at which the median statistic's season
reliability reaches `TARGET`, on the tuning seeds.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date

from ml.pro.gaps import TeamRow
from ml.pro.seasons import SeasonRow, from_league

REFERENCE = date(2026, 10, 26)
THRESHOLDS = [300, 450, 600, 900, 1200, 1500, 1800]
TARGET = 0.7


@dataclass
class Halves:
    seed: int
    rows: tuple[list[SeasonRow], list[SeasonRow]]
    teams: tuple[list[TeamRow], list[TeamRow]]


def halves(seed: int, reference: date = REFERENCE) -> Halves:
    from data.pipelines.synthetic import pro_league

    clubs, players = pro_league.synthetic_inputs(seed, reference)
    first, second = pro_league.build_halves(seed, clubs, players, reference)
    rows = tuple(from_league(h, players) for h in (first, second))
    teams = tuple([TeamRow(str(t.club_id), t.competition, t.season.label, t.metrics) for t in h.team_seasons]
                  for h in (first, second))
    return Halves(seed, rows, teams)


def _pearson(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3 or statistics.pstdev(a) == 0 or statistics.pstdev(b) == 0:
        return None
    return statistics.correlation(a, b)


def spearman_brown(r: float) -> float:
    return 2 * r / (1 + r) if r > -1 else -1.0


@dataclass
class TeamReliability:
    key: str
    label: str
    r: float | None
    # Of the teams in the bottom third in the first half, the share also there in the second.
    bottom_third_kept: float


def team_reliability(gaps, data: Halves) -> list[TeamReliability]:
    out = []
    first, second = ({t.club: t for t in h} for h in data.teams)
    clubs = sorted(first)
    for metric in gaps.metrics:
        a = [metric.value(first[c].metrics) for c in clubs]
        b = [metric.value(second[c].metrics) for c in clubs]

        lower = metric.better == "lower"
        kept = len(_bottom_third(a, lower) & _bottom_third(b, lower)) / max(1, len(clubs) // 3)
        out.append(TeamReliability(metric.key, metric.label, _pearson(a, b), kept))
    return out


def _bottom_third(values: list[float], lower_is_better: bool) -> set[int]:
    """Indices of the worst third: the lowest values, or the highest when lower is better."""
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=lower_is_better)
    return set(order[: len(values) // 3])


def _z(values: list[float]) -> list[float]:
    mean, sd = statistics.fmean(values), statistics.pstdev(values)
    return [(v - mean) / sd if sd else 0.0 for v in values]


def player_reliability(gaps, data: Halves, threshold: int) -> dict[str, tuple[float | None, int]]:
    """attribute -> (half-season correlation within group, players), for players with
    threshold / 2 minutes or more in each half."""
    first = {r.player_id: r for r in data.rows[0]}
    second = {r.player_id: r for r in data.rows[1]}
    both = [pid for pid in first if pid in second
            and min(first[pid].minutes, second[pid].minutes) >= threshold / 2
            and gaps.group_of(first[pid].position) is not None]
    out = {}
    for key, attr in gaps.attributes.items():
        xs, ys = [], []
        for group in gaps.groups.values():
            if key not in group.attributes:
                continue
            pairs = [(attr.value(first[p].metrics), attr.value(second[p].metrics))
                     for p in both if gaps.group_of(first[p].position) == group.key]
            pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
            if len(pairs) < 3:
                continue
            xs += _z([x for x, _ in pairs])
            ys += _z([y for _, y in pairs])
        out[key] = (_pearson(xs, ys), len(xs))
    return out


def choose_min_minutes(by_threshold: dict[int, dict[str, float | None]]) -> int | None:
    """The smallest threshold whose median season reliability reaches TARGET."""
    for threshold in sorted(by_threshold):
        values = [spearman_brown(r) for r in by_threshold[threshold].values() if r is not None]
        if values and statistics.median(values) >= TARGET:
            return threshold
    return None
