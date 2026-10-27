"""A synthetic Egyptian Premier League: three seasons of team and player statistics, shaped like
what FootyStats publishes, with an answer key for the pro tier's analyses.

Decision 0003 and the pro tier cards. The pro tier is built and evaluated on this until the
FootyStats subscription is live; the adapter will write real seasons into the same records
(`football.season_aggregate.v2` for players, `football.team_season.v1` in team_season_stat).

How it is made
--------------
- **18 clubs, 24 players each**, by position (3 goalkeepers, 4 centre backs, 2 of each full
  back, 2 defensive, 3 central and 2 attacking midfielders, 2 of each winger, 2 strikers).
- **Every player has a latent quality** and a few attributes (attack, creativity, defending,
  passing, dribbling, aerial, finishing), which change with age each season: growth to 24, a
  plateau, a decline after 30.
- **Planted breakouts**: about 8% of players aged 18 to 23 get a large jump in quality in one
  season, and their minutes follow. They are the answer key for the breakout detector.
- **Finishing**: most players' goals scatter around their expected goals by chance; about 4% are
  genuinely better finishers and 4% worse. So scoring above your xG mostly does not last, which
  is the real-world pattern the sustainability analysis must cope with.
- **Matches are simulated**, a double round robin of 34 a season: each side's expected goals
  from the two teams' strength, goals drawn from them. Team seasons are the sums. A player's
  goals, shots, expected goals and assists are shares of their team's, so team and player
  figures agree: a team's players' goals add up to the team's goals.
- **Players abroad** (the diaspora tier) get seasons in their own clubs' leagues, from rates,
  since their teams are not simulated.

Everything is drawn from streams seeded by the seed alone, so a seed always makes the same
league. It is separate from `generate.py`, whose dataset the detectors are scored on: nothing
here changes that dataset or any published number.

    python -m data.pipelines.synthetic.pro_league --database-url postgresql+psycopg://...
"""

from __future__ import annotations

import argparse
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import date

COMPETITION = "Egyptian Premier League"
LEAGUE_SIZE = 18
SEASONS = 3
MATCH_MINUTES = 90
SQUAD = {"GK": 3, "CB": 4, "LB": 2, "RB": 2, "CDM": 2, "CM": 3, "CAM": 2, "LW": 2, "RW": 2, "ST": 2}
# How many of each position start a match (4-3-3 with a holding midfielder).
STARTERS = {"GK": 1, "CB": 2, "LB": 1, "RB": 1, "CDM": 1, "CM": 2, "CAM": 0, "LW": 1, "RW": 1, "ST": 1}
# The shared club list (reference.CLUB_NAME_PARTS_AR) has 16 names; the league has 18 clubs.
MORE_CLUBS = ["زد", "مودرن سبورت", "بتروجت", "حرس الحدود"]
SOURCE = "api"
SCHEMA_PLAYER = "football.season_aggregate.v2"
SCHEMA_TEAM = "football.team_season.v1"
BREAKOUT_RATE = 0.08
BREAKOUT_JUMP = 1.1

# Per-position profiles: share of the team's chances, of its chance creation, and per-90 rates.
ATTACK = {"GK": 0.0, "CB": 0.1, "LB": 0.1, "RB": 0.1, "CDM": 0.12, "CM": 0.25, "CAM": 0.55,
          "LW": 0.65, "RW": 0.65, "ST": 1.0}
CREATE = {"GK": 0.02, "CB": 0.1, "LB": 0.4, "RB": 0.4, "CDM": 0.3, "CM": 0.6, "CAM": 1.0,
          "LW": 0.8, "RW": 0.8, "ST": 0.45}
PASSES = {"GK": 28, "CB": 55, "LB": 45, "RB": 45, "CDM": 60, "CM": 55, "CAM": 45, "LW": 32, "RW": 32, "ST": 22}
PASS_RATE = {"GK": 0.72, "CB": 0.87, "LB": 0.79, "RB": 0.79, "CDM": 0.86, "CM": 0.84, "CAM": 0.78,
             "LW": 0.75, "RW": 0.75, "ST": 0.7}
CROSSES = {"GK": 0.0, "CB": 0.1, "LB": 2.5, "RB": 2.5, "CDM": 0.3, "CM": 0.6, "CAM": 0.8,
           "LW": 3.0, "RW": 3.0, "ST": 0.4}
DRIBBLES = {"GK": 0.0, "CB": 0.3, "LB": 1.1, "RB": 1.1, "CDM": 0.6, "CM": 0.9, "CAM": 2.2,
            "LW": 3.2, "RW": 3.2, "ST": 1.6}
TACKLES = {"GK": 0.05, "CB": 1.6, "LB": 2.0, "RB": 2.0, "CDM": 2.6, "CM": 1.8, "CAM": 0.9,
           "LW": 0.8, "RW": 0.8, "ST": 0.5}
INTERCEPTIONS = {"GK": 0.1, "CB": 1.5, "LB": 1.1, "RB": 1.1, "CDM": 1.4, "CM": 0.9, "CAM": 0.5,
                 "LW": 0.4, "RW": 0.4, "ST": 0.3}
DUELS = {"GK": 1.0, "CB": 7.0, "LB": 7.0, "RB": 7.0, "CDM": 8.0, "CM": 7.0, "CAM": 6.0,
         "LW": 7.0, "RW": 7.0, "ST": 8.0}
AERIAL_SHARE = {"GK": 0.5, "CB": 0.5, "LB": 0.15, "RB": 0.15, "CDM": 0.3, "CM": 0.2, "CAM": 0.1,
                "LW": 0.1, "RW": 0.1, "ST": 0.4}
CLEARANCES = {"GK": 0.8, "CB": 4.5, "LB": 2.0, "RB": 2.0, "CDM": 1.5, "CM": 0.6, "CAM": 0.3,
              "LW": 0.3, "RW": 0.3, "ST": 0.3}
YELLOWS = {"GK": 0.06, "CB": 0.22, "LB": 0.2, "RB": 0.2, "CDM": 0.25, "CM": 0.18, "CAM": 0.13,
           "LW": 0.12, "RW": 0.12, "ST": 0.14}
PENALTY_XG = 0.76


@dataclass
class Club:
    id: uuid.UUID
    name: str


@dataclass
class Pro:
    id: uuid.UUID
    position: str
    date_of_birth: date
    club_id: uuid.UUID
    # The competition the player's club plays in; the Egyptian league unless they are abroad.
    competition: str = COMPETITION


@dataclass
class Season:
    label: str
    start: date
    end: date


@dataclass
class PlayerSeason:
    player_id: uuid.UUID
    club_id: uuid.UUID
    competition: str
    season: Season
    metrics: dict


@dataclass
class TeamSeason:
    club_id: uuid.UUID
    competition: str
    season: Season
    metrics: dict


@dataclass
class League:
    clubs: list[Club]
    seasons: list[Season]
    player_seasons: list[PlayerSeason]
    team_seasons: list[TeamSeason]
    # The answer key: planted breakouts as (player id, season label), and each player's true
    # finishing (1.0 is ordinary) and quality by season.
    breakouts: set[tuple[str, str]] = field(default_factory=set)
    finishing: dict[str, float] = field(default_factory=dict)
    quality: dict[tuple[str, str], float] = field(default_factory=dict)


def seasons_before(reference: date, count: int = SEASONS) -> list[Season]:
    """The `count` completed seasons before `reference`: August 1 to May 31."""
    last_end_year = reference.year if (reference.month, reference.day) >= (6, 1) else reference.year - 1
    out = []
    for i in range(count):
        end_year = last_end_year - (count - 1 - i)
        out.append(Season(f"{end_year - 1}/{str(end_year)[-2:]}", date(end_year - 1, 8, 1), date(end_year, 5, 31)))
    return out


def _age(dob: date, on: date) -> float:
    return (on - dob).days / 365.25


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _binomial(rng: random.Random, n: int, p: float) -> int:
    p = min(1.0, max(0.0, p))
    return sum(rng.random() < p for _ in range(n))


def _share(rng: random.Random, total: int, weights: list[float]) -> list[int]:
    """`total` counts split across `weights` (a multinomial draw)."""
    out = [0] * len(weights)
    mass = sum(weights)
    if mass <= 0 or total <= 0:
        return out
    cumulative, run = [], 0.0
    for w in weights:
        run += w / mass
        cumulative.append(run)
    for _ in range(total):
        r = rng.random()
        for i, c in enumerate(cumulative):
            if r <= c:
                out[i] += 1
                break
        else:
            out[-1] += 1
    return out


@dataclass
class _Person:
    pro: Pro
    quality: float
    attack: float
    create: float
    defend: float
    passing: float
    dribbling: float
    aerial: float
    finishing: float


def _growth(age: float) -> float:
    if age < 21:
        return 0.25
    if age < 24:
        return 0.12
    if age < 30:
        return 0.0
    if age < 33:
        return -0.1
    return -0.2


def build_league(seed: int, clubs: list[Club], players: list[Pro], reference: date) -> League:
    """The league's three seasons for these clubs and players. Deterministic in `seed`."""
    rng = random.Random(f"pro-league:{seed}")
    seasons = seasons_before(reference)
    league = League(clubs=clubs, seasons=seasons, player_seasons=[], team_seasons=[])

    people = {}
    for pro in sorted(players, key=lambda p: str(p.id)):
        prng = random.Random(f"pro-player:{seed}:{pro.id}")
        quality = prng.gauss(0, 1)
        roll = prng.random()
        finishing = prng.lognormvariate(0, 0.06) * (1.3 if roll < 0.04 else 0.75 if roll < 0.08 else 1.0)
        # Attack, creativity, defending, passing, dribbling, aerial: each partly the player's quality.
        attributes = [0.6 * quality + 0.8 * prng.gauss(0, 1) for _ in range(6)]
        people[pro.id] = _Person(pro, quality, *attributes, finishing)
        league.finishing[str(pro.id)] = round(finishing, 3)

    clubs_by_id = {c.id: c for c in clubs}
    club_strength = {c.id: rng.gauss(0, 0.25) for c in clubs}

    for index, season in enumerate(seasons):
        # Age the squad: growth, decline and the planted breakouts.
        for person in people.values():
            age = _age(person.pro.date_of_birth, season.end)
            if index > 0:
                person.quality += _growth(age) + rng.gauss(0, 0.15)
                if 18 <= age < 24 and rng.random() < BREAKOUT_RATE:
                    person.quality += BREAKOUT_JUMP
                    person.attack += BREAKOUT_JUMP
                    person.create += BREAKOUT_JUMP * 0.6
                    league.breakouts.add((str(person.pro.id), season.label))
            league.quality[(str(person.pro.id), season.label)] = round(person.quality, 3)

        minutes = _minutes(rng, people, season)
        home = [p for p in people.values() if p.pro.competition == COMPETITION and p.pro.club_id in clubs_by_id]
        strength = {}
        for club in clubs:
            squad = [p for p in home if p.pro.club_id == club.id]
            played = sorted(squad, key=lambda p: -minutes[p.pro.id])[:11]
            strength[club.id] = club_strength[club.id] + (
                sum(p.quality for p in played) / max(1, len(played))
            ) * 0.35
        teams = _simulate(rng, clubs, strength)
        for club in clubs:
            league.team_seasons.append(TeamSeason(club.id, COMPETITION, season, teams[club.id]))
            squad = [p for p in home if p.pro.club_id == club.id]
            for pro_id, metrics in _allocate(rng, squad, minutes, teams[club.id], season).items():
                league.player_seasons.append(PlayerSeason(pro_id, club.id, COMPETITION, season, metrics))
        # Players abroad: their teams are not simulated, so from rates in a nominal team.
        for person in (p for p in people.values() if p.pro.competition != COMPETITION):
            metrics = _abroad(rng, person, minutes[person.pro.id], season)
            if metrics:
                league.player_seasons.append(
                    PlayerSeason(person.pro.id, person.pro.club_id, person.pro.competition, season, metrics)
                )
    return league


def _minutes(rng: random.Random, people: dict, season: Season) -> dict[uuid.UUID, int]:
    """Minutes by squad role: within a club and position, the better players start."""
    out = {}
    groups: dict[tuple, list[_Person]] = {}
    for person in people.values():
        groups.setdefault((person.pro.club_id, person.pro.position), []).append(person)
    full = 34 * MATCH_MINUTES
    for (_, position), members in groups.items():
        members.sort(key=lambda p: -p.quality)
        starters = STARTERS.get(position, 1) or 0
        for rank, person in enumerate(members):
            if rank < starters:
                share = rng.gauss(0.82, 0.1)
            elif rank == starters:
                share = rng.gauss(0.32, 0.12) if starters else rng.gauss(0.55, 0.15)
            else:
                share = rng.gauss(0.07, 0.06)
            out[person.pro.id] = int(min(full, max(0, share * full)))
    return out


def _simulate(rng: random.Random, clubs: list[Club], strength: dict) -> dict[uuid.UUID, dict]:
    """A double round robin; each team's season totals."""
    fields = ("matches wins draws losses points goals_for goals_against shots_for shots_against "
              "clean_sheets home_points away_points goals_for_first_half goals_against_first_half "
              "goals_against_last_15 set_piece_goals_for set_piece_goals_against").split()
    totals = {c.id: {f: 0 for f in fields} | {"xg_for": 0.0, "xg_against": 0.0, "possession_sum": 0.0}
              for c in clubs}
    for home in clubs:
        for away in clubs:
            if home.id == away.id:
                continue
            gap = strength[home.id] - strength[away.id]
            sides = {}
            for team, sign, edge in ((home.id, 1, 0.12), (away.id, -1, -0.12)):
                xg = math.exp(math.log(1.2) + 0.45 * sign * gap + edge) * rng.lognormvariate(0, 0.25)
                goals = _poisson(rng, xg)
                sides[team] = (round(xg, 2), goals, _poisson(rng, xg / 0.105))
            possession = min(80.0, max(20.0, 50 + 12 * math.tanh(gap) + rng.gauss(0, 4)))
            for team, other, own_possession, is_home in (
                (home.id, away.id, possession, True), (away.id, home.id, 100 - possession, False),
            ):
                xg, goals, shots = sides[team]
                xg_a, conceded, shots_a = sides[other]
                row = totals[team]
                row["matches"] += 1
                row["goals_for"] += goals
                row["goals_against"] += conceded
                row["xg_for"] += xg
                row["xg_against"] += xg_a
                row["shots_for"] += max(shots, goals)
                row["shots_against"] += max(shots_a, conceded)
                row["possession_sum"] += own_possession
                row["clean_sheets"] += conceded == 0
                row["goals_for_first_half"] += _binomial(rng, goals, 0.45)
                row["goals_against_first_half"] += _binomial(rng, conceded, 0.45)
                row["goals_against_last_15"] += _binomial(rng, conceded, 0.22)
                row["set_piece_goals_for"] += _binomial(rng, goals, 0.25)
                row["set_piece_goals_against"] += _binomial(rng, conceded, 0.25)
                points = 3 if goals > conceded else 1 if goals == conceded else 0
                row["wins"] += points == 3
                row["draws"] += points == 1
                row["losses"] += points == 0
                row["points"] += points
                row["home_points" if is_home else "away_points"] += points
    out = {}
    for team, row in totals.items():
        matches = row["matches"] or 1
        out[team] = {k: v for k, v in row.items() if k != "possession_sum"} | {
            "xg_for": round(row["xg_for"], 2),
            "xg_against": round(row["xg_against"], 2),
            "possession_pct": round(row["possession_sum"] / matches, 1),
        }
    return out


def _per90(rng: random.Random, rate: float, minutes: int, skill: float = 0.0, spread: float = 0.2) -> int:
    return _poisson(rng, rate * math.exp(spread * skill) * minutes / MATCH_MINUTES)


def _rest(rng: random.Random, person: _Person, minutes: int) -> dict:
    """The statistics that do not depend on the team's goals: passing, duels, defending."""
    pos = person.pro.position
    passes = _per90(rng, PASSES[pos], minutes, person.passing, 0.15)
    rate = min(0.95, max(0.5, PASS_RATE[pos] + 0.03 * person.passing + rng.gauss(0, 0.015)))
    dribbles = _per90(rng, DRIBBLES[pos], minutes, person.dribbling, 0.25)
    duels = _per90(rng, DUELS[pos], minutes, 0, 0)
    aerials = min(duels, _binomial(rng, duels, AERIAL_SHARE[pos]))
    return {
        "key_passes": 0,
        "passes_attempted": passes,
        "passes_completed": _binomial(rng, passes, rate),
        "crosses": _per90(rng, CROSSES[pos], minutes, person.create, 0.2),
        "dribbles_attempted": dribbles,
        "dribbles_completed": _binomial(rng, dribbles, 0.45 + 0.05 * person.dribbling),
        "tackles": _per90(rng, TACKLES[pos], minutes, person.defend, 0.2),
        "interceptions": _per90(rng, INTERCEPTIONS[pos], minutes, person.defend, 0.2),
        "duels": duels,
        "duels_won": _binomial(rng, duels, 0.5 + 0.04 * person.quality),
        "aerial_duels": aerials,
        "aerial_duels_won": _binomial(rng, aerials, 0.5 + 0.06 * person.aerial),
        "clearances": _per90(rng, CLEARANCES[pos], minutes, person.defend, 0.15),
        "yellow_cards": _per90(rng, YELLOWS[pos], minutes, 0, 0),
        "red_cards": _poisson(rng, 0.008 * minutes / MATCH_MINUTES),
    }


def _appearances(rng: random.Random, minutes: int) -> tuple[int, int]:
    if minutes <= 0:
        return 0, 0
    starter = minutes > 1200
    apps = round(minutes / (80 if starter else 30)) + rng.randint(0, 2)
    apps = min(34, max(apps, math.ceil(minutes / MATCH_MINUTES)))
    starts = min(apps, round(minutes / 88) if starter else round(apps * 0.25))
    return apps, starts


def _allocate(rng, squad: list[_Person], minutes: dict, team: dict, season: Season) -> dict:
    """A team's goals, chances, shots and assists shared among its players by role and minutes."""
    playing = [p for p in squad if minutes[p.pro.id] > 0]
    if not playing:
        return {}
    penalties = _poisson(rng, 4.5)
    pens_scored = _binomial(rng, penalties, 0.78)
    taker = max(playing, key=lambda p: (ATTACK[p.pro.position] > 0.5, p.finishing, minutes[p.pro.id]))
    npxg_team = max(0.0, team["xg_for"] - penalties * PENALTY_XG)
    np_goals = max(0, team["goals_for"] - pens_scored)

    weight = {p.pro.id: ATTACK[p.pro.position] * minutes[p.pro.id] * math.exp(0.35 * p.attack) for p in playing}
    total = sum(weight.values()) or 1
    npxg = {pid: npxg_team * w / total for pid, w in weight.items()}
    goal_split = _share(rng, np_goals, [npxg[p.pro.id] * p.finishing for p in playing])
    shot_split = _share(rng, max(team["shots_for"] - penalties, np_goals),
                        [npxg[p.pro.id] * rng.lognormvariate(0, 0.2) for p in playing])
    creates = {p.pro.id: CREATE[p.pro.position] * minutes[p.pro.id] * math.exp(0.35 * p.create) for p in playing}
    create_total = sum(creates.values()) or 1
    xa = {pid: 0.75 * npxg_team * w / create_total for pid, w in creates.items()}
    assist_split = _share(rng, round(team["goals_for"] * 0.72), [xa[p.pro.id] for p in playing])

    out = {}
    for i, person in enumerate(playing):
        pid = person.pro.id
        goals = goal_split[i] + (pens_scored if person is taker else 0)
        pen_xg = penalties * PENALTY_XG if person is taker else 0.0
        shots = max(shot_split[i] + (penalties if person is taker else 0), goals)
        on_target = min(shots, goals + _binomial(rng, shots - goals, 0.22))
        apps, starts = _appearances(rng, minutes[pid])
        metrics = {
            "appearances": apps,
            "starts": starts,
            "minutes_played": minutes[pid],
            "goals": goals,
            "penalty_goals": pens_scored if person is taker else 0,
            "xg": round(npxg[pid] + pen_xg, 2),
            "npxg": round(npxg[pid], 2),
            "assists": assist_split[i],
            "xa": round(xa[pid], 2),
            "shots": shots,
            "shots_on_target": on_target,
        } | _rest(rng, person, minutes[pid])
        metrics["key_passes"] = max(assist_split[i], _poisson(rng, xa[pid] / 0.11))
        out[pid] = metrics
    return out


def _abroad(rng, person: _Person, minutes: int, season: Season) -> dict | None:
    """A season abroad, from rates in a nominal team: about 1.25 expected goals a match."""
    if minutes <= 0:
        return None
    pos = person.pro.position
    matches = minutes / MATCH_MINUTES
    npxg = 1.25 * matches * ATTACK[pos] * math.exp(0.35 * person.attack) / 3.4
    xa = 0.75 * 1.25 * matches * CREATE[pos] * math.exp(0.35 * person.create) / 4.0
    goals = _poisson(rng, npxg * person.finishing)
    shots = max(goals, _poisson(rng, npxg / 0.1))
    assists = _poisson(rng, xa)
    apps, starts = _appearances(rng, minutes)
    metrics = {
        "appearances": apps, "starts": starts, "minutes_played": minutes, "goals": goals,
        "penalty_goals": 0, "xg": round(npxg, 2), "npxg": round(npxg, 2), "assists": assists,
        "xa": round(xa, 2), "shots": shots,
        "shots_on_target": min(shots, goals + _binomial(rng, shots - goals, 0.22)),
    } | _rest(rng, person, minutes)
    metrics["key_passes"] = max(assists, _poisson(rng, xa / 0.11))
    return metrics


# ---------------------------------------------------------------------------
# Inputs without a database (evaluations), and the database loader
# ---------------------------------------------------------------------------


def synthetic_inputs(seed: int, reference: date) -> tuple[list[Club], list[Pro]]:
    """Clubs and squads made from the seed alone, for evaluating the analyses."""
    rng = random.Random(f"pro-inputs:{seed}")
    clubs = [Club(uuid.UUID(int=rng.getrandbits(128)), f"Club {i + 1}") for i in range(LEAGUE_SIZE)]
    players = []
    for club in clubs:
        for position, count in SQUAD.items():
            for _ in range(count):
                players.append(Pro(uuid.UUID(int=rng.getrandbits(128)), position,
                                   _birth_date(rng, reference), club.id))
    return clubs, players


def _birth_date(rng: random.Random, reference: date) -> date:
    age = min(36.0, max(17.5, rng.gauss(25.5, 4.0)))
    return date.fromordinal(reference.toordinal() - int(age * 365.25))


def load(database_url: str, seed: int = 20261027, reference: date | None = None) -> int:
    """Fill the Egyptian league to 18 clubs of 24, then write three seasons. Once: a database
    that already has league seasons is left alone. Returns the player seasons written."""
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import Session

    from . import orm  # noqa: F401  (puts apps/api on the path)
    from app import sports
    from app.models.consent import Consent
    from app.models.enums import ConsentPurpose
    from app.models.measurement import Measurement
    from app.models.organization import Organization
    from app.models.performance_entry import PerformanceEntry
    from app.models.player import Player
    from app.models.player_organization import PlayerOrganization
    from app.models.team_season_stat import TeamSeasonStat

    from .reference import CLUB_NAME_PARTS_AR
    from .regions import region_for
    from .rng import Rng

    reference = reference or date.today()
    engine = create_engine(database_url, future=True)
    with Session(engine) as db:
        done = db.execute(
            select(func.count()).select_from(PerformanceEntry).where(PerformanceEntry.schema_ref == SCHEMA_PLAYER)
        ).scalar_one()
        if done:
            return 0

        federation = db.execute(
            select(Organization).where(Organization.type == "federation", Organization.sport == "football",
                                       Organization.country == "EG")
        ).scalars().first()
        clubs_rows = list(db.execute(
            select(Organization).where(Organization.type == "club", Organization.sport == "football",
                                       Organization.country == "EG").order_by(Organization.name)
        ).scalars())
        taken = {c.name for c in db.execute(select(Organization)).scalars()}
        rng = Rng(seed)
        for name in CLUB_NAME_PARTS_AR + MORE_CLUBS:
            if len(clubs_rows) >= LEAGUE_SIZE:
                break
            if name in taken:
                continue
            club = Organization(id=rng.uuid(), name=name, type="club", sport="football", country="EG",
                                parent_org_id=federation.id if federation else None,
                                region=region_for(name, "club", "EG"), external_ids={"source": "synthetic"})
            db.add(club)
            clubs_rows.append(club)
        db.flush()
        clubs = [Club(c.id, c.name) for c in clubs_rows[:LEAGUE_SIZE]]
        club_ids = {c.id for c in clubs}

        current = list(db.execute(
            select(Player, PlayerOrganization.organization_id, Organization.country)
            .join(PlayerOrganization, PlayerOrganization.player_id == Player.id)
            .join(Organization, Organization.id == PlayerOrganization.organization_id)
            .where(PlayerOrganization.end_date.is_(None))
            .where(Player.primary_sport == "football", Player.status == "active")
            .where(Player.tier.in_(["pro", "diaspora"]))
        ).all())
        pros = []
        filled: dict[tuple, int] = {}
        for player, org_id, country in current:
            if player.position not in SQUAD or player.date_of_birth is None:
                continue
            if org_id in club_ids and player.tier == "pro":
                pros.append(Pro(player.id, player.position, player.date_of_birth, org_id))
                filled[(org_id, player.position)] = filled.get((org_id, player.position), 0) + 1
            elif player.tier == "diaspora":
                pros.append(Pro(player.id, player.position, player.date_of_birth, org_id,
                                competition=f"League abroad ({country})"))

        # Fill each squad to its shape with adult Egyptian players who signed up themselves.
        start = date(seasons_before(reference)[0].start.year - 1, 7, 1)
        for club in clubs:
            for position, count in SQUAD.items():
                for _ in range(count - filled.get((club.id, position), 0)):
                    dob = _birth_date(rng.random, reference)
                    player = Player(
                        id=rng.uuid(), full_name=rng.faker.eg_full_name("male"), date_of_birth=dob,
                        sex="male", nationality=["EG"], is_egypt_eligible=True, primary_sport="football",
                        tier="pro", position=position, is_minor=False, status="active", external_ids={},
                    )
                    db.add(player)
                    db.add(PlayerOrganization(id=rng.uuid(), player_id=player.id, organization_id=club.id,
                                              role="player", start_date=start, end_date=None))
                    for purpose in (ConsentPurpose.DATA_STORAGE, ConsentPurpose.ANALYTICS,
                                    ConsentPurpose.SCOUTING_VISIBILITY):
                        db.add(Consent(id=rng.uuid(), player_id=player.id, purpose=purpose.value, granted=True,
                                       granted_by="player", valid_from=start))
                    # A club measures its players at the start of each season and midway: four
                    # readings over two years, steady, as an adult's height is (measuring error
                    # about half a centimetre).
                    height = min(198.0, max(165.0, rng.gauss(179, 6)))
                    for days_ago in (700, 520, 340, 160):
                        db.add(Measurement(
                            id=rng.uuid(), player_id=player.id,
                            measured_at=date.fromordinal(reference.toordinal() - days_ago),
                            metric="height_cm", value=round(height + rng.gauss(0, 0.4), 1), unit="cm",
                            source=SOURCE, confidence="measured",
                        ))
                    pros.append(Pro(player.id, position, dob, club.id))
        db.flush()

        league = build_league(seed, clubs, pros, reference)
        modules = sports.registry()
        written = 0
        for row in league.team_seasons:
            assert not sports.validate(row.metrics, SCHEMA_TEAM, modules), row.metrics
            db.add(TeamSeasonStat(organization_id=row.club_id, sport="football", competition=row.competition,
                                  season=row.season.label, period_start=row.season.start,
                                  period_end=row.season.end, schema_ref=SCHEMA_TEAM, metrics=row.metrics,
                                  source=SOURCE))
        for row in league.player_seasons:
            assert not sports.validate(row.metrics, SCHEMA_PLAYER, modules), row.metrics
            db.add(PerformanceEntry(
                id=uuid.uuid4(), player_id=row.player_id, sport="football", period_type="season_aggregate",
                period_start=row.season.start, period_end=row.season.end, organization_id=row.club_id,
                event=f"{row.competition} {row.season.label}", metrics=row.metrics, schema_ref=SCHEMA_PLAYER,
                source=SOURCE, is_validated=True,
            ))
            written += 1
        db.commit()
        return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    written = load(args.database_url)
    print(f"pro league: wrote {written} player seasons" if written
          else "pro league: already present, nothing written")


if __name__ == "__main__":
    main()
