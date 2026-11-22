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

Leagues with basic player data
------------------------------
FootyStats, the source of the Egyptian league, publishes a player's season as appearances,
minutes, goals, assists and cards only (`football.season_basic.v1`, decision 0009). For a
league with no full player seasons, the club view runs the same engine on the basic config
(`teamGaps.basic` in the sport module): the source's position groups, non-penalty goals and
assists per 90, and candidates only for the weakness those answer (chances made). Every other
weakness says no basic statistic answers it.

A goal or assist rate over one season is mostly chance, so basic players are ranked on their
talent estimate (`ml/estimates`, graded in ml/README.md, "Talent estimates"), computed exactly
as the profile's "Against league peers" (`app/services/estimates.py`): the same peers
(analytics consent, the same league, season and position group, 90+ minutes), the same prior,
at least 20 peers. A player's percentile here is the profile's. A player is ranked from 90
minutes, the estimates' peer rule, instead of the 450 that guards raw rates.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import sports
from app.models.enums import ConsentPurpose
from app.models.organization import Organization
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.models.team_season_stat import TeamSeasonStat
from app.services import estimates, pro
from app.services import forecast  # noqa: F401  (puts ml/ on the path)
from app.services.access import Caller, consent_subquery, may_view

from ml.estimates import shrinkage  # noqa: E402
from ml.pro import gaps as engine  # noqa: E402
from ml.pro.seasons import SeasonRow  # noqa: E402


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


def _consented(db: Session) -> set[str]:
    return {str(pid) for pid in db.execute(consent_subquery(ConsentPurpose.ANALYTICS.value)).scalars()}


def _player_rows(db: Session) -> list:
    """Every league season of a player whose analytics consent is in effect."""
    consented = _consented(db)
    return [r for r in pro._rows(db) if r.player_id in consented]


def _basic_rows(db: Session, league: tuple[str, str] | None = None) -> list[SeasonRow]:
    """Every basic league season of a player whose analytics consent is in effect, its position
    the source's position group, with each estimated attribute's talent estimate on it. With
    `league` (competition, season), that league season's only: a prior fit per position group
    and statistic is the slow part."""
    basic = _config().basic
    consented = _consented(db)
    rows = []
    query = (select(PerformanceEntry, Player.date_of_birth).join(Player, Player.id == PerformanceEntry.player_id)
             .where(PerformanceEntry.schema_ref == basic.player_period))
    for entry, dob in db.execute(query).all():
        if str(entry.player_id) not in consented:
            continue
        season = pro._season(entry.event, entry.period_start, entry.period_end)
        competition = pro._competition(entry.event, season)
        if league is not None and (competition, season) != league:
            continue
        rows.append(SeasonRow(
            player_id=str(entry.player_id), season=season, end=entry.period_end, competition=competition,
            club=str(entry.organization_id) if entry.organization_id else None,
            position=entry.metrics.get(basic.position_field), date_of_birth=dob,
            metrics=dict(entry.metrics), source=entry.source,
        ))

    groups: dict[tuple, list[SeasonRow]] = defaultdict(list)
    for r in rows:
        if basic.group_of(r.position):
            groups[(r.competition, r.season, r.position)].append(r)
    for members in groups.values():
        peers = [r for r in members if r.minutes >= estimates.MIN_PEER_MINUTES]
        for attr in (a for a in basic.attributes.values() if a.estimated):
            fit = [(int(c), r.minutes / 90) for r in peers if (c := attr.count(r.metrics)) is not None]
            if len(fit) < estimates.MIN_PEERS:
                continue
            prior = shrinkage.fit_prior([c for c, _ in fit], [e for _, e in fit])
            for r in members:
                count = attr.count(r.metrics)
                # The peers are the others: the profile's rule (app/services/estimates.py).
                others = len(fit) - (1 if r.minutes >= estimates.MIN_PEER_MINUTES else 0)
                if count is not None and others >= estimates.MIN_PEERS:
                    r.metrics[attr.key] = (int(count) + prior.k * prior.mean) / (r.minutes / 90 + prior.k)
    return rows


def _basis(db: Session, competition: str, season: str):
    """(config, rows, minimum minutes) for a league season: the full analysis when it has full
    player seasons, else the basic one when it has basic seasons."""
    config = _config()
    rows = _player_rows(db)
    if config.basic is not None and not any(r.competition == competition and r.season == season for r in rows):
        basic = _basic_rows(db, (competition, season))
        if basic:
            return config.basic, basic, estimates.MIN_PEER_MINUTES
    return config, rows, engine.MIN_MINUTES


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
    configs = [(config, False)] + ([(config.basic, True)] if config.basic else [])
    return {
        "clubs": sorted(clubs.values(), key=lambda c: c["name"]),
        "groups": [{"key": g.key, "label": g.label, "attributes": g.attributes, "basic": basic}
                   for c, basic in configs for g in c.groups.values()],
        "attributes": [{"key": a.key, "label": a.label, "lowReliability": a.low_reliability, "percent": not a.per90,
                        "estimated": a.estimated}
                       for c, _ in configs for a in c.attributes.values()],
        "minMinutes": engine.MIN_MINUTES,
        "minCohort": engine.MIN_COHORT,
        "basicMinMinutes": estimates.MIN_PEER_MINUTES,
        "basicMinPeers": estimates.MIN_PEERS,
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


def _needs(needs: list[engine.Need], people, clubs, basic: set[str] = frozenset()) -> list[dict]:
    out = []
    for need in needs:
        out.append({
            "group": need.group, "label": need.label, "attributes": need.attributes, "basic": need.group in basic,
            "candidates": [c for c in (_candidate(x, people, clubs) for x in need.candidates) if c],
            "unranked": [c for c in (_candidate(x, people, clubs) for x in need.unranked) if c],
        })
    return out


def club(db: Session, caller: Caller, club_id: uuid.UUID, season: str | None) -> dict:
    teams = _team_rows(db)
    mine = [t for t in teams if t.club == str(club_id)]
    if not mine:
        raise NotFound
    season = season or max(t.season for t in mine)
    team = next((t for t in mine if t.season == season), None)
    if team is None:
        raise NotFound
    config, rows, min_minutes = _basis(db, team.competition, season)
    basic = config is _config().basic
    profile = engine.team_profile(config, teams, team.club, team.competition, season)
    coverage = engine.squad_coverage(config, rows, team.club, team.competition, season, min_minutes=min_minutes)
    needs = engine.club_needs(config, profile, rows, team.club, team.competition, season, min_minutes=min_minutes)

    ids = {p.player_id for g in coverage for p in g.players}
    ids |= {c.player_id for ns in needs.values() for n in ns for c in [*n.candidates, *n.unranked]}
    people = _people(db, caller, ids)
    clubs = _club_names(db, {team.club} | {c.club for ns in needs.values() for n in ns
                                           for c in n.candidates if c.club})
    return {
        "club": {"id": team.club, "name": clubs.get(team.club), "competition": team.competition, "season": season},
        "basic": basic,
        "profile": [
            {"key": m.key, "label": m.label, "value": m.value, "rank": m.rank, "of": m.of, "better": m.better,
             "weak": m.weak, "bottomUnstable": m.bottom_unstable, "percent": m.percent,
             "noPlayerLink": m.no_player_link,
             "needs": _needs(needs.get(m.key, []), people, clubs, set(config.groups) if basic else set())}
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
        "minMinutes": min_minutes,
    }


def national(db: Session, caller: Caller, asks: list[tuple[str, list[str]]]) -> dict:
    """`asks`: (group, attributes) pairs the federation chose, from the full config's groups or
    the basic one's (players with basic seasons). Raises ValueError on an unknown one."""
    full = _config()
    basic = full.basic
    chosen = []
    for group, attributes in asks:
        config = full if group in full.groups else basic if basic and group in basic.groups else None
        if config is None or not attributes or any(a not in config.attributes for a in attributes):
            raise ValueError(f"unknown position group or statistic in {group}:{','.join(attributes)}")
        chosen.append(config)
    full_rows = _player_rows(db) if any(c is full for c in chosen) else []
    basic_rows = _basic_rows(db) if any(c is not full for c in chosen) else []
    eligible = {str(pid) for pid in db.execute(
        select(Player.id).where(Player.is_egypt_eligible.is_(True), Player.primary_sport == "football")).scalars()}
    needs = [engine.candidates(config, full_rows if config is full else basic_rows, group, attributes,
                               competition=None, season=None, pool=eligible, limit=10,
                               min_minutes=engine.MIN_MINUTES if config is full else estimates.MIN_PEER_MINUTES)
             for config, (group, attributes) in zip(chosen, asks)]
    ids = {c.player_id for n in needs for c in [*n.candidates, *n.unranked]}
    people = _people(db, caller, ids)
    clubs = _club_names(db, {c.club for n in needs for c in [*n.candidates, *n.unranked] if c.club})
    return {"needs": _needs(needs, people, clubs, set(basic.groups) if basic else set()),
            "minMinutes": engine.MIN_MINUTES}
