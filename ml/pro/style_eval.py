"""Does "plays most like" find real style? (ml/pro/style.py)

The test: split each season in two by date. A player's first half, compared with every
player's second half in the same position group, should find their own second half near the
top, because a player's style is more like their own than like anyone else's. If the method
only matched noise, their own half would sit at a random rank.

Scored per position group and overall: how often the own half is the closest (top 1), among the
5 and 10 closest, its median rank, and the mean reciprocal rank; against what a random ordering
gives for the same pool sizes. Real players only (StatsBomb, decision 0008); the same
standardisation and cosine as the app (`style.standardiser`, `style.cosine`).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from ml.pro import style
from ml.pro.seasons import SeasonRow

MIN_HALF_MINUTES = 450


@dataclass
class Result:
    group: str
    players: int
    top1: float
    top5: float
    top10: float
    median_rank: float
    mrr: float
    # The same, for a random ordering of the same pools.
    random_top1: float
    random_top5: float
    random_top10: float
    random_median_rank: float
    random_mrr: float


def ranks(config, first: list[SeasonRow], second: list[SeasonRow]) -> dict[str, list[tuple[str, int, int]]]:
    """group -> (player, rank of their own second half among the group's second halves, pool size).

    Both halves need MIN_HALF_MINUTES and the same position group; a player's group is read from
    their position, which the caller sets from the whole season."""
    out: dict[str, list[tuple[str, int, int]]] = {}
    by_key = {(r.player_id, r.competition): r for r in second}
    for group in config.groups:
        firsts = [r for r in first if config.group_of(r.position) == group and r.minutes >= MIN_HALF_MINUTES
                  and (r.player_id, r.competition) in by_key
                  and by_key[(r.player_id, r.competition)].minutes >= MIN_HALF_MINUTES]
        if len(firsts) < 10:
            continue
        candidates = [by_key[(r.player_id, r.competition)] for r in firsts]
        # Standardised across both halves of the players being compared, so neither half sets
        # the scale alone.
        scale = style.standardiser(config, firsts + candidates)
        scaled = [scale(c) for c in candidates]
        rows = []
        for r, own in zip(firsts, candidates):
            me = scale(r)
            scores = [style.cosine(me, v) for v in scaled]
            own_score = scores[candidates.index(own)]
            rank = 1 + sum(1 for s in scores if s > own_score)
            rows.append((r.player_id, rank, len(candidates)))
        out[group] = rows
    return out


def _random(sizes: list[int]) -> tuple[float, float, float, float, float]:
    """Expected scores of a random ordering: rank uniform on 1..n."""
    top = [lambda n, k=k: min(k, n) / n for k in (1, 5, 10)]
    mrr = statistics.fmean(sum(1 / r for r in range(1, n + 1)) / n for n in sizes)
    median = statistics.median((n + 1) / 2 for n in sizes)
    return (statistics.fmean(top[0](n) for n in sizes), statistics.fmean(top[1](n) for n in sizes),
            statistics.fmean(top[2](n) for n in sizes), median, mrr)


def score(group: str, rows: list[tuple[str, int, int]]) -> Result:
    rs = [r for _, r, _ in rows]
    sizes = [n for _, _, n in rows]
    rand = _random(sizes)
    return Result(
        group=group, players=len(rows),
        top1=sum(r == 1 for r in rs) / len(rs), top5=sum(r <= 5 for r in rs) / len(rs),
        top10=sum(r <= 10 for r in rs) / len(rs), median_rank=statistics.median(rs),
        mrr=statistics.fmean(1 / r for r in rs),
        random_top1=rand[0], random_top5=rand[1], random_top10=rand[2], random_median_rank=rand[3], random_mrr=rand[4],
    )


def evaluate(config, first: list[SeasonRow], second: list[SeasonRow]) -> list[Result]:
    """One Result per position group, then "all" over every player."""
    by_group = ranks(config, first, second)
    results = [score(g, rows) for g, rows in by_group.items()]
    everyone = [row for rows in by_group.values() for row in rows]
    if everyone:
        results.append(score("all", everyone))
    return results
