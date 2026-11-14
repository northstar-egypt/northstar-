"""League seasons on the profile: finishing against expected goals, trends, and breakouts.

This file holds no analysis of its own. It reads the player's league seasons
(`football.season_aggregate.v2`) and runs `ml/pro`, the code `python -m ml.run_pro_eval` scores
against the synthetic league's answer key (ml/README.md, "Pro tier"). So what the profile shows
is exactly what was evaluated.

- **Analytics consent.** Judging a player's seasons is analytics on their data, so a player
  without analytics consent in effect gets a note and nothing else.
- **The team's totals.** The breakout detector measures a player's share of their team's
  chances, so it reads every league season of the player's clubs. Only the club's sum is used,
  and it is a team figure of the kind `team_season_stat` publishes, never another player's row.
"""

from __future__ import annotations

import re

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ConsentPurpose
from app.models.organization import Organization
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.services import forecast  # noqa: F401  (puts ml/ on the path)
from app.services.access import has_consent

from ml.pro import breakout, sustainability, trends  # noqa: E402
from ml.pro.seasons import SeasonRow  # noqa: E402

SCHEMA = "football.season_aggregate.v2"


def _competition(event: str | None, season: str) -> str:
    """"Egyptian Premier League 2025/26" -> "Egyptian Premier League"."""
    text = (event or "").strip()
    return text[: -len(season)].strip() if text.endswith(season) else text or "League"


def _label(start: date, end: date) -> str:
    """"2025/26" for a league season; "2018" for a tournament played within one year."""
    if start.year == end.year:
        return str(start.year)
    return f"{start.year}/{str(end.year)[-2:]}"


# A season named at the end of an entry's event: "... 2025/26" or "... 2023".
_SEASON_AT_END = re.compile(r"(\d{4}(?:/\d{2})?)$")


def _season(event: str | None, start: date, end: date) -> str:
    """The season an entry names, else one made from its dates. A tournament's name wins over
    its dates: the 2023 African Cup of Nations was played in January and February 2024."""
    found = _SEASON_AT_END.search((event or "").strip())
    return found.group(1) if found else _label(start, end)


def _rows(db: Session, player_ids: list | None = None, club_ids: list | None = None) -> list[SeasonRow]:
    query = (
        select(PerformanceEntry, Player.position, Player.date_of_birth)
        .join(Player, Player.id == PerformanceEntry.player_id)
        .where(PerformanceEntry.schema_ref == SCHEMA)
    )
    if player_ids is not None:
        query = query.where(PerformanceEntry.player_id.in_(player_ids))
    if club_ids is not None:
        query = query.where(PerformanceEntry.organization_id.in_(club_ids))
    out = []
    for entry, position, dob in db.execute(query).all():
        season = _season(entry.event, entry.period_start, entry.period_end)
        out.append(SeasonRow(
            player_id=str(entry.player_id), season=season, end=entry.period_end,
            competition=_competition(entry.event, season),
            club=str(entry.organization_id) if entry.organization_id else None,
            position=position, date_of_birth=dob, metrics=entry.metrics,
        ))
    return out


def _finishing(f: sustainability.Finishing) -> dict:
    return {"npGoals": f.np_goals, "npxg": f.npxg, "low": f.low, "high": f.high,
            "verdict": f.verdict, "seasons": f.seasons}


def player_seasons(db: Session, player: Player) -> dict:
    if not has_consent(db, player.id, ConsentPurpose.ANALYTICS.value):
        return {"seasons": [], "career": None, "trends": [], "note":
                "Analytics consent is not in effect for this player, so their seasons are not analysed."}
    mine = _rows(db, player_ids=[player.id])
    if not mine:
        return {"seasons": [], "career": None, "trends": [], "note": "No league seasons on record."}

    clubs = {r.club for r in mine if r.club}
    team_rows = _rows(db, club_ids=list(clubs)) if clubs else []
    # Seasons are compared with the one before, in the same competition, only from the second
    # season that competition's data covers.
    first_year: dict[str, int] = {}
    for event, start, end in db.execute(
        select(PerformanceEntry.event, PerformanceEntry.period_start, PerformanceEntry.period_end)
        .where(PerformanceEntry.schema_ref == SCHEMA)
    ).all():
        name = _competition(event, _season(event, start, end))
        first_year[name] = min(first_year.get(name, end.year), end.year)
    teams = breakout.team_totals(team_rows)
    names = dict(db.execute(select(Organization.id, Organization.name)
                            .where(Organization.id.in_(list(clubs)))).all()) if clubs else {}

    mine.sort(key=lambda r: (r.end, r.competition))
    by_end = {(r.competition, r.end.year): r for r in mine}
    seasons = []
    for row in mine:
        previous = by_end.get((row.competition, row.end.year - 1))
        entry = {
            "season": row.season,
            "competition": row.competition,
            "club": next((n for k, n in names.items() if str(k) == row.club), None),
            "minutes": row.minutes,
            "finishing": _finishing(sustainability.season(row)),
            "breakout": None,
        }
        if row.end.year > first_year.get(row.competition, row.end.year):
            a = breakout.assess(previous, row, teams)
            entry["breakout"] = {"flagged": a.flagged, "score": a.score, "reason": a.reason,
                                 "considered": a.score is not None}
        seasons.append(entry)

    return {
        "seasons": list(reversed(seasons)),
        "career": _finishing(sustainability.career(mine)),
        "trends": [
            {"season": t.season, "previous": t.previous, "minutesBefore": t.minutes_before,
             "minutesAfter": t.minutes_after,
             "changes": [{"key": c.key, "label": c.label, "before": c.before, "after": c.after,
                          "unit": c.unit} for c in t.changes]}
            for t in reversed(trends.player_trends(mine, first_year))
        ],
        "note": None,
    }
