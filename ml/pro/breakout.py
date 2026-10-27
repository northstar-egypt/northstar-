"""Breakout detector, v1: young players whose season stepped clearly above their last.

What a breakout looks like in league numbers
--------------------------------------------
A player who gets much better takes and makes a bigger part of their team's chances. That is
measured against the player's own previous season, never against other players, so a striker
and a centre back are each judged on their own scale:

- **involvement**: non-penalty expected goals plus expected assists (npxG + xA) per 90 minutes,
  as a share of the team's npxG + xA per match. Expected rather than actual goals, because goals
  are mostly chance and expected goals move with what the player does. A share of the team's
  rather than a bare rate, because when a whole club improves every player's rate rises with
  it, and that is not a breakout. The team's total is the sum of its players' seasons on record.
- **change**: a log ratio of this season's involvement to last season's, so doubling counts the
  same for a winger and a centre back (a small floor keeps a centre back's tiny share from
  counting as a doubling).

A season is flagged when the change reaches `THRESHOLD`, chosen on the tuning seeds (101, 202,
303) and nothing else; see ml/README.md, "Pro tier", for the grid, the version this replaced
(a bare per-90 rate) and the scores on the reporting seeds.

What it cannot see
------------------
- Involvement needs `MIN_MINUTES` in both seasons. A player who barely played last season has
  nothing to compare against, so a breakout from the bench is missed and the reason says so.
- It needs the team: a season at a club with fewer than `MIN_TEAM_PLAYERS` players on record
  (a player abroad, whose club's other players are not in the data) is not scored.
- Only players aged `MIN_AGE` to under `MAX_AGE` at the end of the season are considered. That
  is the scouting meaning of a breakout, and it is also exactly the window the synthetic answer
  key plants breakouts in; the README reports the score without the age window too, so the gain
  from it is visible rather than hidden.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ml.pro.seasons import FULL_SEASON_MINUTES, SeasonRow, by_player, consecutive

MIN_AGE = 18
MAX_AGE = 24
MIN_MINUTES = 270
MIN_TEAM_PLAYERS = 11
MATCHES = 34
# About a twentieth of a typical team's npxG + xA per match.
FLOOR = 0.025
THRESHOLD = 0.11


@dataclass(frozen=True)
class Assessment:
    player_id: str
    season: str
    # None when the season cannot be scored; `reason` then says why.
    score: float | None
    flagged: bool
    # Share of the team's npxG + xA, per 90 against per match; None when not measurable.
    involvement_before: float | None
    involvement_after: float | None
    minutes_before: int
    minutes_after: int
    reason: str


TeamTotals = dict[tuple[str, str, str], tuple[int, float]]


def team_totals(rows: list[SeasonRow]) -> TeamTotals:
    """(club, competition, season) -> (players on record, their npxG + xA summed)."""
    out: dict[tuple[str, str, str], tuple[int, float]] = {}
    for row in rows:
        if row.club is None:
            continue
        key = (row.club, row.competition, row.season)
        players, total = out.get(key, (0, 0.0))
        out[key] = (players + 1, total + row.metrics["npxg"] + row.metrics["xa"])
    return out


def involvement(row: SeasonRow | None, teams: TeamTotals) -> float | None:
    """The player's npxG + xA per 90 as a share of the team's per match; None without enough
    minutes or without the team on record."""
    if row is None or row.minutes < MIN_MINUTES or row.club is None:
        return None
    players, total = teams.get((row.club, row.competition, row.season), (0, 0.0))
    if players < MIN_TEAM_PLAYERS or total <= 0:
        return None
    return (row.metrics["npxg"] + row.metrics["xa"]) * 90 / row.minutes / (total / MATCHES)


def assess(
    previous: SeasonRow | None,
    this: SeasonRow,
    teams: TeamTotals,
    threshold: float = THRESHOLD,
    age_window: bool = True,
) -> Assessment:
    before, after = involvement(previous, teams), involvement(this, teams)
    minutes_before = previous.minutes if previous else 0
    common = dict(
        player_id=this.player_id, season=this.season, involvement_before=before,
        involvement_after=after, minutes_before=minutes_before, minutes_after=this.minutes,
    )
    age = this.age
    if age_window and (age is None or not MIN_AGE <= age < MAX_AGE):
        return Assessment(score=None, flagged=False, reason="outside the breakout age window", **common)
    if this.minutes < MIN_MINUTES:
        return Assessment(score=None, flagged=False,
                          reason=f"fewer than {MIN_MINUTES} minutes this season", **common)
    if after is None:
        return Assessment(score=None, flagged=False,
                          reason="the rest of the team is not on record to compare against", **common)
    if previous is None or previous.minutes < MIN_MINUTES:
        return Assessment(score=None, flagged=False,
                          reason=f"fewer than {MIN_MINUTES} minutes the season before, so nothing "
                          "to compare against", **common)
    if before is None:
        return Assessment(score=None, flagged=False,
                          reason="last season's team is not on record to compare against", **common)
    value = math.log((after + FLOOR) / (before + FLOOR))
    if value >= threshold:
        reason = (f"accounted for {before:.1%} of the team's chances (npxG + xA) per 90 minutes "
                  f"played the season before and {after:.1%} this season, a rise of {after / before - 1:.0%}"
                  if before > 0 else
                  f"accounted for {after:.1%} of the team's chances (npxG + xA) per 90 minutes, "
                  "from none the season before")
    else:
        reason = "no clear step up on the season before"
    return Assessment(score=round(value, 3), flagged=value >= threshold, reason=reason, **common)


def detect(
    rows: list[SeasonRow],
    first_year: int,
    threshold: float = THRESHOLD,
    age_window: bool = True,
) -> list[Assessment]:
    """Every season after the first that the detector considers, flagged or not."""
    teams = team_totals(rows)
    out = []
    for seasons in by_player(rows).values():
        for previous, this in consecutive(seasons, first_year):
            out.append(assess(previous, this, teams, threshold, age_window))
    return out


def per90_detect(rows: list[SeasonRow], first_year: int, threshold: float = 0.15,
                 minutes_weight: float = 0.1) -> set[tuple[str, str]]:
    """The first version, kept as a comparison: npxG + xA per 90 as a bare rate (floor 0.05),
    plus `minutes_weight` times the rise in the share of a full season played. Its settings
    are its own best on the tuning seeds."""

    def rate(row):
        if row is None or row.minutes < MIN_MINUTES:
            return None
        return (row.metrics["npxg"] + row.metrics["xa"]) * 90 / row.minutes

    out = set()
    for seasons in by_player(rows).values():
        for previous, this in consecutive(seasons, first_year):
            age = this.age
            after = rate(this)
            if age is None or not MIN_AGE <= age < MAX_AGE or after is None:
                continue
            before = rate(previous)
            change = math.log((after + 0.05) / (before + 0.05)) if before is not None else 0.0
            rise = (this.minutes - (previous.minutes if previous else 0)) / FULL_SEASON_MINUTES
            if change + minutes_weight * rise >= threshold:
                out.add((this.player_id, this.season))
    return out


def minutes_only(rows: list[SeasonRow], first_year: int, threshold: float) -> set[tuple[str, str]]:
    """The baseline: flag a young player whose share of a full season rose by `threshold`."""
    out = set()
    for seasons in by_player(rows).values():
        for previous, this in consecutive(seasons, first_year):
            age = this.age
            if age is None or not MIN_AGE <= age < MAX_AGE:
                continue
            rise = (this.minutes - (previous.minutes if previous else 0)) / FULL_SEASON_MINUTES
            if rise >= threshold:
                out.add((this.player_id, this.season))
    return out
