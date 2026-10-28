"""Team gap analysis for the web app (decision 0003), running `ml/pro/gaps.py` on the database.

The analysis is the ML module's; this file loads the rows, applies the access rules, and puts
names on the results.

- **Who sees it**: scouts and federation staff (the router enforces it). Coaches and players do
  not, as proposed in decision 0003.
- **Analytics consent**: only players whose analytics consent is in effect are ranked or used
  as the population a percentile is among, as for the profile's radar.
- **Who may see whom**: a squad member or candidate the caller may not see (`access.may_view`)
  is left out, so the list never reveals a withheld player.
- **National team mode**: the pool is every Egypt-eligible player with a league season, at
  home or abroad, each ranked only among their own league's players.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import sports
from app.models.enums import ConsentPurpose
from app.models.organization import Organization
from app.models.player import Player
from app.models.team_season_stat import TeamSeasonStat
from app.services import forecast  # noqa: F401  (puts ml/ on the path)
from app.services import pro
from app.services.access import Caller, consent_subquery, may_view

from ml.pro import gaps as engine  # noqa: E402


# The league national team mode calls home; any other is shown as abroad.
HOME_COMPETITION = "Egyptian Premier League"


class NotFound(Exception):
    pass


def _config():
    return sports.registry()["football"].team_gaps


def _team_rows(db: Session) -> list[engine.TeamRow]:
    config = _config()
    return [
        engine.TeamRow(str(t.organization_id), t.competition, t.season, t.metrics)
        for t in db.execute(select(TeamSeasonStat).where(TeamSeasonStat.schema_ref == config.team_period)).scalars()
    ]


def _player_rows(db: Session) -> list:
    """Every league season of a player whose analytics consent is in effect."""
    consented = {str(pid) for pid in db.execute(consent_subquery(ConsentPurpose.ANALYTICS.value)).scalars()}
    return [r for r in pro._rows(db) if r.player_id in consented]


def _people(db: Session, caller: Caller, ids: set[str]) -> dict[str, Player]:
    """The players among `ids` the caller may see, by id."""
    if not ids:
        return {}
    players = db.execute(select(Player).where(Player.id.in_([uuid.UUID(i) for i in ids]))).scalars()
    return {str(p.id): p for p in players if may_view(db, caller, p)[0]}


def _club_names(db: Session, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = db.execute(select(Organization.id, Organization.name)
                      .where(Organization.id.in_([uuid.UUID(i) for i in ids if i]))).all()
    return {str(k): v for k, v in rows}


def options(db: Session) -> dict:
    """The clubs with team seasons, and what national team mode can ask for."""
    config = _config()
    teams = _team_rows(db)
    names = _club_names(db, {t.club for t in teams})
    clubs: dict[str, dict] = {}
    for t in teams:
        entry = clubs.setdefault(t.club, {"id": t.club, "name": names.get(t.club, "Unknown club"),
                                          "competition": t.competition, "seasons": []})
        entry["seasons"].append(t.season)
    for entry in clubs.values():
        entry["seasons"].sort(reverse=True)
    return {
        "clubs": sorted(clubs.values(), key=lambda c: c["name"]),
        "groups": [{"key": g.key, "label": g.label, "attributes": g.attributes} for g in config.groups.values()],
        "attributes": [{"key": a.key, "label": a.label, "lowReliability": a.low_reliability, "percent": not a.per90}
                       for a in config.attributes.values()],
        "minMinutes": engine.MIN_MINUTES,
        "minCohort": engine.MIN_COHORT,
    }


def _candidate(c: engine.Candidate, people: dict[str, Player], clubs: dict[str, str]) -> dict | None:
    player = people.get(c.player_id)
    if player is None:
        return None
    return {
        "playerId": c.player_id, "fullName": player.full_name, "position": player.position,
        "club": clubs.get(c.club or ""), "competition": c.competition, "season": c.season,
        "minutes": c.minutes,
        "values": {k: (round(v, 3) if v is not None else None) for k, v in c.values.items()},
        "percentiles": c.percentiles, "mean": c.mean, "population": c.population,
        "abroad": c.competition != HOME_COMPETITION,
    }


def _needs(needs: list[engine.Need], people, clubs) -> list[dict]:
    out = []
    for need in needs:
        out.append({
            "group": need.group, "label": need.label, "attributes": need.attributes,
            "candidates": [c for c in (_candidate(x, people, clubs) for x in need.candidates) if c],
            "unranked": [c for c in (_candidate(x, people, clubs) for x in need.unranked) if c],
        })
    return out


def club(db: Session, caller: Caller, club_id: uuid.UUID, season: str | None) -> dict:
    config = _config()
    teams = _team_rows(db)
    mine = [t for t in teams if t.club == str(club_id)]
    if not mine:
        raise NotFound
    season = season or max(t.season for t in mine)
    team = next((t for t in mine if t.season == season), None)
    if team is None:
        raise NotFound
    rows = _player_rows(db)
    profile = engine.team_profile(config, teams, team.club, team.competition, season)
    coverage = engine.squad_coverage(config, rows, team.club, team.competition, season)
    needs = engine.club_needs(config, profile, rows, team.club, team.competition, season)

    ids = {p.player_id for g in coverage for p in g.players}
    ids |= {c.player_id for ns in needs.values() for n in ns for c in [*n.candidates, *n.unranked]}
    people = _people(db, caller, ids)
    clubs = _club_names(db, {team.club} | {c.club for ns in needs.values() for n in ns
                                           for c in n.candidates if c.club})
    return {
        "club": {"id": team.club, "name": clubs.get(team.club), "competition": team.competition, "season": season},
        "profile": [
            {"key": m.key, "label": m.label, "value": m.value, "rank": m.rank, "of": m.of, "better": m.better,
             "weak": m.weak, "bottomUnstable": m.bottom_unstable, "percent": m.percent,
             "noPlayerLink": m.no_player_link, "needs": _needs(needs.get(m.key, []), people, clubs)}
            for m in profile
        ],
        "coverage": [
            {"group": g.group, "label": g.label, "attributes": g.attributes, "population": g.population,
             "players": [{"playerId": p.player_id, "fullName": people[p.player_id].full_name,
                          "position": people[p.player_id].position, "minutes": p.minutes, "share": round(p.share, 3),
                          "percentiles": p.percentiles, "ranked": p.ranked}
                         for p in g.players if p.player_id in people]}
            for g in coverage
        ],
        "minMinutes": engine.MIN_MINUTES,
    }


def national(db: Session, caller: Caller, asks: list[tuple[str, list[str]]]) -> dict:
    """`asks`: (group, attributes) pairs the federation chose. Raises ValueError on an unknown one."""
    config = _config()
    for group, attributes in asks:
        if group not in config.groups or not attributes or any(a not in config.attributes for a in attributes):
            raise ValueError(f"unknown position group or statistic in {group}:{','.join(attributes)}")
    rows = _player_rows(db)
    eligible = {str(pid) for pid in db.execute(
        select(Player.id).where(Player.is_egypt_eligible.is_(True), Player.primary_sport == "football")).scalars()}
    needs = [engine.candidates(config, rows, group, attributes, competition=None, season=None, pool=eligible, limit=10)
             for group, attributes in asks]
    ids = {c.player_id for n in needs for c in [*n.candidates, *n.unranked]}
    people = _people(db, caller, ids)
    clubs = _club_names(db, {c.club for n in needs for c in [*n.candidates, *n.unranked] if c.club})
    return {"needs": _needs(needs, people, clubs), "minMinutes": engine.MIN_MINUTES}
