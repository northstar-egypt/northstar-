"""From performance rows to rated matches, and from matches to ratings over time.

A match between two registered players can arrive as two rows, one logged by each side, that
mirror each other. It is one match and counts once.

Which matches count toward a rating
-----------------------------------
A rating moves with every win over a strong player, so a claimed win is worth faking. A match
counts only when something other than the player's own word stands behind it:

- at least one of its rows came from a source that is not self-submitted (the results feed,
  a scrape, or a coach), or
- both players logged it, and the two rows agree.

A self-submitted win that the opponent never confirmed still shows on the player's own
record. It just does not move anyone's rating. Rows that fail their sport module (a match both
players won) never count.

Matches against someone who is not on the platform have no opponent to rate against and are
left out here; they still count in the player's own results.

Ratings over time
-----------------
Glicko-2 updates in rating periods. Here a period is a calendar month: everyone's matches in
the month are rated against their opponents' ratings as they stood at the start of it, and a
player with no matches that month only grows less certain. `history` keeps the rating each
player had going into every month, which is what a walk-forward evaluation needs (predict a
match from ratings that existed before it), and what the profile needs to show an opponent's
rating at the time of a match.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from ml import sport_modules
from ml.rating import glicko2
from ml.rating.glicko2 import Game, Rating

SELF_SUBMITTED = "self_submitted"


@dataclass(frozen=True)
class Match:
    played_on: date
    winner: str
    loser: str
    best_of: int
    confirmed: bool  # counts toward a rating (see the module docstring)
    entry_ids: tuple[str, ...]


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _won(metrics: dict) -> bool:
    return metrics["sets_won"] > metrics["sets_lost"]


def collect(rows: list[dict]) -> list[Match]:
    """Every match between two registered players, once each, in date order.

    `rows` are performance entries as dicts (the JSON export, or the database rows), any sport;
    only rows with an `opponent_player_id` and a valid record are used.
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        opponent = row.get("opponent_player_id")
        metrics = row.get("metrics") or {}
        if not opponent or "sets_won" not in metrics:
            continue
        if sport_modules.impossibilities(metrics, row.get("schema_ref", "")):
            continue
        player = str(row["player_id"])
        opponent = str(opponent)
        winner, loser = (player, opponent) if _won(metrics) else (opponent, player)
        # The two rows of one match agree on this key; a disagreement is two different claims.
        key = (
            _as_date(row["period_start"]),
            winner,
            loser,
            metrics["best_of"],
            tuple(sorted((metrics["points_won"], metrics["points_lost"]))),
        )
        groups[key].append(row)

    matches = []
    for (played_on, winner, loser, best_of, _points), group in groups.items():
        sides = {str(r["player_id"]) for r in group}
        confirmed = len(sides) == 2 or any(r.get("source") != SELF_SUBMITTED for r in group)
        matches.append(
            Match(
                played_on=played_on,
                winner=winner,
                loser=loser,
                best_of=best_of,
                confirmed=confirmed,
                entry_ids=tuple(sorted(str(r["id"]) for r in group)),
            )
        )
    matches.sort(key=lambda m: (m.played_on, m.entry_ids))
    return matches


def _month(d: date) -> date:
    return d.replace(day=1)


def _next_month(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


@dataclass
class RatingHistory:
    """Each player's rating going into each month, from the first rated month on."""

    first_month: date | None = None
    last_month: date | None = None
    # month -> player -> rating at the start of that month
    by_month: dict[date, dict[str, Rating]] = field(default_factory=dict)
    # player -> rating after the last month
    current: dict[str, Rating] = field(default_factory=dict)
    rated_matches: dict[str, int] = field(default_factory=dict)

    def before(self, player: str, when: date) -> Rating | None:
        """The rating a player had going into the month of `when`, if they had one by then."""
        month = self.by_month.get(_month(when))
        if month is None:
            return self.current.get(player) if self.last_month and when > self.last_month else None
        return month.get(player)


def history(matches: list[Match], *, until: date | None = None, tau: float = glicko2.TAU) -> RatingHistory:
    """Run Glicko-2 month by month over the confirmed matches.

    A player enters at the default rating in the month of their first rated match. `until`
    carries the idle months forward to that date, so a rating's uncertainty reflects how long
    ago the player last played.
    """
    rated = [m for m in matches if m.confirmed]
    out = RatingHistory()
    if not rated:
        return out
    by_month: dict[date, list[Match]] = defaultdict(list)
    for m in rated:
        by_month[_month(m.played_on)].append(m)

    month = min(by_month)
    last = max(by_month)
    if until is not None:
        last = max(last, _month(until))
    out.first_month = month
    ratings: dict[str, Rating] = {}
    while month <= last:
        out.by_month[month] = dict(ratings)
        games: dict[str, list[Game]] = defaultdict(list)
        for m in by_month.get(month, []):
            w = ratings.get(m.winner, Rating())
            l = ratings.get(m.loser, Rating())  # noqa: E741
            games[m.winner].append(Game(l, 1.0))
            games[m.loser].append(Game(w, 0.0))
            out.rated_matches[m.winner] = out.rated_matches.get(m.winner, 0) + 1
            out.rated_matches[m.loser] = out.rated_matches.get(m.loser, 0) + 1
        everyone = set(ratings) | set(games)
        ratings = {
            p: glicko2.update(ratings.get(p, Rating()), games.get(p, []), tau=tau)
            for p in everyone
        }
        month = _next_month(month)
    out.last_month = last
    out.current = ratings
    return out
