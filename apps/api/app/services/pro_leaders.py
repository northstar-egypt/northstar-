"""Leaders of one professional league season, from the basic season records.

The professional tier's real source, FootyStats (decision 0009), publishes per player and
season only appearances, minutes, goals, assists, cards, clean sheets and goals conceded. They
are stored as `football.season_basic.v1`. This module ranks the players of one league season
on what that record holds, for the Ask screen ("top scorers in the Premier League 2023/24").

The rules, so that no number is made up:

- **Only what the source publishes is ranked**: goals, assists, goals per 90, assists per 90,
  minutes and appearances (`PUBLISHED`). A statistic it does not publish (expected goals,
  shots, passes, tackles, distance) is answered with why, not with a ranking of something else
  (`NOT_PUBLISHED`).
- **Per 90 only from 450 minutes**, five full matches. Below that one goal in a 20 minute cameo
  is 4.5 goals per 90, which says nothing. How many were left out is said.
- **Ages are on the season's first day** (the entry's `period_start`). A player with no date of
  birth on record is left out of an age-filtered ranking, and counted.
- **Position group is the source's own label for that season** (`position_group` in the
  record), the only position FootyStats gives for outfield players.
- **Only players the caller may open**: `visible_players`, then `may_view` per player, as the
  other screens do.

`rank` is the ranking itself, on plain rows, so it is tested without a database
(tests/test_pro_leaders.py). `leaders` finds the rows for a league and season and calls it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.services.access import Caller, may_view, visible_players
from app.services.pro import BASIC, _competition, _season

MIN_MINUTES_PER_90 = 450
LIMIT = 10

# key -> (label, the record's field it is computed from, per 90 or not)
PUBLISHED: dict[str, tuple[str, str, bool]] = {
    "goals": ("Goals", "goals", False),
    "assists": ("Assists", "assists", False),
    "goals_per_90": ("Goals per 90", "goals", True),
    "assists_per_90": ("Assists per 90", "assists", True),
    "minutes_played": ("Minutes", "minutes_played", False),
    "appearances": ("Appearances", "appearances", False),
}

# Statistics people ask about that the basic record does not have.
NOT_PUBLISHED: dict[str, str] = {
    "xg": "expected goals (xG)",
    "shots": "shots",
    "key_passes": "chances created",
    "passes_attempted": "passes",
    "pass_completion": "passing accuracy",
    "tackles": "tackles",
    "distance_km": "distance covered",
}

# The leagues a question can name, matched against the competition names on record. Egypt is
# checked first: "Egyptian Premier League" also contains "Premier League".
LEAGUES: dict[str, tuple[str, re.Pattern]] = {
    "egyptian_premier_league": ("Egyptian Premier League", re.compile(r"egypt", re.I)),
    "liga_mx": ("Liga MX", re.compile(r"liga\s*mx|mexic", re.I)),
    "england_premier_league": ("Premier League (England)", re.compile(r"premier league", re.I)),
}


class ProLeadersError(Exception):
    """The question cannot be answered as asked; the message says why and what would work."""


@dataclass
class SeasonLine:
    """One player's basic season, as `rank` needs it."""

    player_id: str
    name: str
    club: str | None
    season_start: date
    date_of_birth: date | None
    metrics: dict


def age_on(day: date, born: date) -> int:
    return day.year - born.year - ((day.month, day.day) < (born.month, born.day))


def rank(
    lines: list[SeasonLine], *, statistic: str, position_group: str | None = None,
    age_from: int | None = None, age_to: int | None = None, limit: int = LIMIT,
) -> dict:
    """The top `limit` lines on one published statistic, highest first.

    Returns {"leaders": [...], "considered": n, "left_out": {reason: count}}. Ties are ordered
    by fewer minutes (the same total in less time), then by name, so the order is stable."""
    if statistic not in PUBLISHED:
        raise ValueError(f"not a published statistic: {statistic}")
    _, field, per_90 = PUBLISHED[statistic]
    left_out: dict[str, int] = {}

    def leave(reason: str) -> None:
        left_out[reason] = left_out.get(reason, 0) + 1

    scored = []
    for line in lines:
        m = line.metrics
        if position_group and m.get("position_group") != position_group:
            continue
        if age_from is not None or age_to is not None:
            if line.date_of_birth is None:
                leave("no date of birth on record")
                continue
            age = age_on(line.season_start, line.date_of_birth)
            if (age_from is not None and age < age_from) or (age_to is not None and age > age_to):
                continue
        else:
            age = age_on(line.season_start, line.date_of_birth) if line.date_of_birth else None
        minutes = m.get("minutes_played") or 0
        if field not in m:
            leave("statistic not on record")
            continue
        if per_90:
            if minutes < MIN_MINUTES_PER_90:
                leave(f"under {MIN_MINUTES_PER_90} minutes")
                continue
            value = round(m[field] * 90 / minutes, 2)
        else:
            value = m[field]
        scored.append((value, minutes, line, age))

    scored.sort(key=lambda s: (-s[0], s[1], s[2].name))
    return {
        "leaders": [
            {
                "player_id": line.player_id, "name": line.name, "club": line.club,
                "position_group": line.metrics.get("position_group"), "age": age,
                "value": value, "minutes": minutes,
                "goals": line.metrics.get("goals"), "assists": line.metrics.get("assists"),
            }
            for value, minutes, line, age in scored[:limit]
        ],
        "considered": len(scored),
        "left_out": left_out,
    }


def _on_record(db: Session) -> list[tuple[str, str, date]]:
    """Every (competition, season, last day) with basic seasons, newest first."""
    seen: dict[tuple[str, str], date] = {}
    for event, start, end in db.execute(
        select(PerformanceEntry.event, PerformanceEntry.period_start, PerformanceEntry.period_end)
        .where(PerformanceEntry.schema_ref == BASIC).distinct()
    ).all():
        season = _season(event, start, end or start)
        key = (_competition(event, season), season)
        seen[key] = max(seen.get(key, end or start), end or start)
    return sorted(((c, s, e) for (c, s), e in seen.items()), key=lambda x: x[2], reverse=True)


def league_of(competition: str) -> str | None:
    """The league key a competition name on record is, or None."""
    for key, (_, pattern) in LEAGUES.items():
        if pattern.search(competition):
            return key
    return None


def resolve(on_record: list[tuple[str, str, date]], league: str | None, season: str | None) -> tuple[str, str]:
    """The (competition, season) a question means. Raises ProLeadersError with the choices when
    it names none on record or more than one could be meant. No season means the latest."""
    if not on_record:
        raise ProLeadersError(
            "No professional league seasons are loaded. They come from FootyStats: see "
            "data/pipelines/footystats/README.md."
        )
    rows = on_record
    if league is not None:
        rows = [r for r in rows if league_of(r[0]) == league]
        if not rows:
            loaded = sorted({r[0] for r in on_record})
            raise ProLeadersError(
                f"No {LEAGUES[league][0]} seasons are loaded. Loaded leagues: {', '.join(loaded)}."
            )
    if season is not None:
        exact = [r for r in rows if r[1] == season]
        if not exact:
            options = sorted({r[1] for r in rows if season in r[1]} or {r[1] for r in rows}, reverse=True)
            raise ProLeadersError(
                f"No season {season} is loaded for that league. Seasons on record: {', '.join(options)}."
            )
        rows = exact
    competitions = sorted({r[0] for r in rows})
    if len(competitions) > 1:
        raise ProLeadersError(f"Which league? Seasons on record from: {', '.join(competitions)}.")
    return rows[0][0], rows[0][1]


def leaders(
    db: Session, caller: Caller, *, league: str | None, season: str | None, statistic: str | None,
    position_group: str | None = None, age_from: int | None = None, age_to: int | None = None,
) -> dict:
    """The ranking for one league season, as the caller may see it."""
    if statistic in NOT_PUBLISHED:
        raise ProLeadersError(
            f"League seasons come from FootyStats, which publishes appearances, minutes, goals, "
            f"assists and cards per player, but not {NOT_PUBLISHED[statistic]}. So there is no "
            f"ranking on it. Try goals, assists, goals or assists per 90, minutes or appearances."
        )
    if statistic not in PUBLISHED:
        raise ProLeadersError(
            "Ranked on which statistic? League seasons hold goals, assists, goals or assists per "
            "90, minutes and appearances."
        )
    competition, season = resolve(_on_record(db), league, season)
    event = f"{competition} {season}"
    query = (
        select(PerformanceEntry, Player, Organization.name)
        .join(Player, Player.id == PerformanceEntry.player_id)
        .outerjoin(Organization, Organization.id == PerformanceEntry.organization_id)
        .where(PerformanceEntry.schema_ref == BASIC, PerformanceEntry.event == event)
        .where(Player.id.in_(visible_players(caller).with_only_columns(Player.id)))
    )
    lines, withheld = [], 0
    for entry, player, club in db.execute(query).all():
        if not may_view(db, caller, player)[0]:
            withheld += 1
            continue
        lines.append(SeasonLine(
            player_id=str(player.id), name=player.full_name, club=club,
            season_start=entry.period_start, date_of_birth=player.date_of_birth, metrics=entry.metrics,
        ))
    body = rank(lines, statistic=statistic, position_group=position_group, age_from=age_from, age_to=age_to)
    if withheld:
        body["left_out"]["not players you may open"] = withheld
    return {**body, "competition": competition, "season": season, "statistic": statistic,
            "label": PUBLISHED[statistic][0], "per_90": PUBLISHED[statistic][2]}
