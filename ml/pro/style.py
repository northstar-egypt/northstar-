"""Players whose season looks most like another's: style, not level.

For the scouting report's "plays most like" (decision 0008). Each season is described by the
team-gap statistics of its position group (per 90 or a share, `teamGaps.attributes` in the
sport module); every statistic is standardised across the pool, and seasons are compared by
cosine similarity. So two players can be alike while one is far better: the percentiles say how
good, this says how alike.

The pool is the same position group, enough minutes for the rates to mean something, and the
same data source: real players are compared with real players and the synthetic league with
itself, never across.

Evaluated in ml/pro/style_eval.py (ml/README.md, "Player similarity, professionals"): a
player's first half season finds their own second half among the five closest 42.8% of the time
against 3.1% by chance; weakest for centre backs (20.8%).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ml.pro.seasons import SeasonRow

MIN_MINUTES = 900
SHOWN = 6


@dataclass
class Match:
    player_id: str
    competition: str
    season: str
    club: str | None
    minutes: int
    similarity: float  # cosine, -1 to 1


def _value(attribute, row: SeasonRow) -> float:
    num = sum(row.metrics.get(n, 0) for n in attribute.numerator)
    if attribute.per90:
        return num / row.minutes * 90 if row.minutes else 0.0
    den = sum(row.metrics.get(d, 0) for d in attribute.denominator)
    return num / den if den else 0.0


def standardiser(config, pool: list[SeasonRow]):
    """A function that turns a season into its statistics, each standardised across `pool`."""
    keys = list(config.attributes)
    columns = list(zip(*[[_value(config.attributes[k], r) for k in keys] for r in pool]))
    means = [sum(c) / len(c) for c in columns]
    spreads = [math.sqrt(sum((x - m) ** 2 for x in c) / len(c)) or 1.0 for c, m in zip(columns, means)]

    def scale(row: SeasonRow) -> list[float]:
        return [(_value(config.attributes[k], row) - m) / s for k, m, s in zip(keys, means, spreads)]

    return scale


def cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0


def similar(config, rows: list[SeasonRow], row: SeasonRow, shown: int = SHOWN,
            min_minutes: int = MIN_MINUTES) -> list[Match]:
    """The seasons most like `row`'s, closest first; one per player (their closest season)."""
    group = config.group_of(row.position)
    if group is None or row.minutes < min_minutes:
        return []
    pool = [r for r in rows if config.group_of(r.position) == group and r.minutes >= min_minutes
            and r.source == row.source]
    if len(pool) < 10:
        return []
    scale = standardiser(config, pool)
    me = scale(row)
    best: dict[str, Match] = {}
    for r in pool:
        if r.player_id == row.player_id:
            continue
        score = cosine(me, scale(r))
        if r.player_id not in best or score > best[r.player_id].similarity:
            best[r.player_id] = Match(r.player_id, r.competition, r.season, r.club, r.minutes, round(score, 3))
    return sorted(best.values(), key=lambda m: -m.similarity)[:shown]
