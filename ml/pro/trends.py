"""Season-on-season trends: how a player's rates moved from one league season to the next.

A rate from a few hundred minutes is mostly noise, so a season is only compared when both it and
the season before have `MIN_MINUTES`. The change is reported as the two rates, never as a bare
percentage, because "+100%" from 0.05 to 0.10 tackles per 90 reads as a finding and is not one.
"""

from __future__ import annotations

from dataclasses import dataclass

from ml.pro.seasons import SeasonRow, by_player, consecutive

MIN_MINUTES = 900

# (key, label, how the rate is made). Per 90 unless a share.
RATES = [
    ("npxg", "npxG per 90", "per90"),
    ("goals", "Goals per 90", "per90"),
    ("xa", "xA per 90", "per90"),
    ("key_passes", "Key passes per 90", "per90"),
    ("dribbles_completed", "Dribbles won per 90", "per90"),
    ("tackles", "Tackles per 90", "per90"),
    ("interceptions", "Interceptions per 90", "per90"),
    ("pass_completion", "Pass completion", "share:passes_completed/passes_attempted"),
    ("duels_won_share", "Duels won", "share:duels_won/duels"),
]


@dataclass(frozen=True)
class Change:
    key: str
    label: str
    before: float
    after: float
    # "per 90" or "%".
    unit: str


@dataclass(frozen=True)
class Trend:
    season: str
    previous: str
    minutes_before: int
    minutes_after: int
    changes: list[Change]


def rate(row: SeasonRow, how: str, key: str) -> float | None:
    if how == "per90":
        value = row.per90(key)
        return round(value, 2) if value is not None else None
    numerator, denominator = how.split(":", 1)[1].split("/")
    if not row.metrics.get(denominator):
        return None
    return round(100 * row.metrics[numerator] / row.metrics[denominator], 1)


def player_trends(seasons: list[SeasonRow], first_year: int) -> list[Trend]:
    out = []
    for previous, this in consecutive(seasons, first_year):
        if previous is None or previous.minutes < MIN_MINUTES or this.minutes < MIN_MINUTES:
            continue
        changes = []
        for key, label, how in RATES:
            before, after = rate(previous, how, key), rate(this, how, key)
            if before is not None and after is not None:
                changes.append(Change(key, label, before, after, "per 90" if how == "per90" else "%"))
        out.append(Trend(this.season, previous.season, previous.minutes, this.minutes, changes))
    return out


def trends(rows: list[SeasonRow], first_year: int) -> dict[str, list[Trend]]:
    return {pid: player_trends(seasons, first_year) for pid, seasons in by_player(rows).items()}
