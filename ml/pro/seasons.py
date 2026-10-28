"""One player's league season, the shape every pro analysis reads.

The same record comes from two places: the synthetic league in memory (evaluations, see
`from_league`) and the database (the API, see apps/api/app/services/pro.py). Keeping the
analyses on this one shape is what lets the API show exactly what was evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

FULL_SEASON_MINUTES = 34 * 90


@dataclass(frozen=True)
class SeasonRow:
    player_id: str
    # "2024/25"; seasons sort by `end`, never by label.
    season: str
    end: date
    competition: str
    # The club the season was played for (an organization id), or None if not known.
    club: str | None
    position: str | None
    date_of_birth: date | None
    metrics: dict

    @property
    def minutes(self) -> int:
        return int(self.metrics.get("minutes_played", 0))

    @property
    def age(self) -> float | None:
        if self.date_of_birth is None:
            return None
        return (self.end - self.date_of_birth).days / 365.25

    def per90(self, key: str) -> float | None:
        return self.metrics[key] * 90 / self.minutes if self.minutes else None

    @property
    def np_goals(self) -> int:
        return int(self.metrics["goals"]) - int(self.metrics["penalty_goals"])


def by_player(rows: list[SeasonRow]) -> dict[str, list[SeasonRow]]:
    """Each player's seasons in date order. A player with seasons in two competitions in one
    year (a move) keeps both; analyses that compare consecutive seasons use `consecutive`."""
    out: dict[str, list[SeasonRow]] = {}
    for row in rows:
        out.setdefault(row.player_id, []).append(row)
    for seasons in out.values():
        seasons.sort(key=lambda r: (r.end, r.competition))
    return out


def consecutive(seasons: list[SeasonRow], first_year: int) -> list[tuple[SeasonRow | None, SeasonRow]]:
    """(previous, this) for each of a player's seasons ending after `first_year`, the end year
    of the first season the data covers. Previous is the season ending the year before, or
    None when the player has none that year: they did not play, which is itself information,
    since a breakout can come from the bench."""
    by_end = {r.end.year: r for r in seasons}
    return [(by_end.get(r.end.year - 1), r) for r in seasons if r.end.year > first_year]


def from_league(league, players) -> list[SeasonRow]:
    """Rows from a `pro_league.League` and the `Pro` records it was built from."""
    pros = {p.id: p for p in players}
    return [
        SeasonRow(
            player_id=str(r.player_id),
            season=r.season.label,
            end=r.season.end,
            competition=r.competition,
            club=str(r.club_id),
            position=pros[r.player_id].position,
            date_of_birth=pros[r.player_id].date_of_birth,
            metrics=r.metrics,
        )
        for r in league.player_seasons
    ]
