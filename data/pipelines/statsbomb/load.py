"""Load StatsBomb open data into the platform's database. Decision 0008.

    python -m data.pipelines.statsbomb.load --data-dir D:/northstar-data/statsbomb \\
        --database-url postgresql+psycopg://northstar:northstar@localhost:5432/northstar

The data directory is a copy of StatsBomb's open-data `data/` folder (competitions.json,
matches/, events/, lineups/), for the competitions wanted. It holds real players' data and is
kept outside the repository; nothing from it is ever committed.

What it writes, all with `source = 'statsbomb'`:

- organizations: one per StatsBomb team (a club, or a national team in an international
  competition), found again by `external_ids.statsbomb_team`;
- players: one per StatsBomb player, found again by `external_ids.statsbomb`, with their
  nationality, main position and the clubs they played for. StatsBomb's open data has no dates
  of birth, so `date_of_birth` is left empty and every age-based view says the age is unknown;
- `performance_entry` rows in `football.season_aggregate.v2`, one per player, team and season;
- `team_season_stat` rows in `football.team_season.v1`, one per team and season;
- `match_event` rows, one per shot with its xG, and one per key pass (a pass that led to a
  shot) with where it arrived and its xA (aggregate.py says how each is counted);
- `performance_entry` rows in `football.touch_map.v1`, one per player, team and season: their
  actions counted on a 12 by 8 grid, which the scouting report draws as a heat map.

It can be run again: StatsBomb rows are deleted and written afresh, and players and teams are
matched by their StatsBomb ids, so their platform ids (and anything that points at them) stay.

Before writing it checks every match: the goals counted from its events must equal the
published score. A match that disagrees is reported and its result is taken from the score.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import defaultdict
from datetime import date
from pathlib import Path

from data.pipelines.statsbomb import aggregate
from data.pipelines.statsbomb.countries import iso_code

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "apps" / "api"))

from sqlalchemy import create_engine, delete, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import sports  # noqa: E402
from app.models.consent import Consent  # noqa: E402
from app.models.enums import ConsentPurpose, PerformanceSource  # noqa: E402
from app.models.match_event import MatchEvent  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.performance_entry import PerformanceEntry  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.player_organization import PlayerOrganization  # noqa: E402
from app.models.team_season_stat import TeamSeasonStat  # noqa: E402

SOURCE = PerformanceSource.STATSBOMB.value
SCHEMA_PLAYER = "football.season_aggregate.v2"
SCHEMA_TEAM = "football.team_season.v1"
SCHEMA_TOUCHES = "football.touch_map.v1"
# The legal basis for holding this data is StatsBomb's open-data licence, accepted by the team,
# not a player's own consent. The consent rows say so, so the access rules, which read consent,
# treat these professionals like any other adult professional on the platform.
GRANTED_BY = "statsbomb_open_data_licence"
EGYPT = "EG"


def season_label(statsbomb_season: str) -> str:
    """StatsBomb's season name in the platform's form: "2015/2016" -> "2015/16", "2023" stays.
    The name, not the dates: the 2023 African Cup of Nations was played in 2024."""
    first, _, second = statsbomb_season.partition("/")
    return f"{first}/{second[-2:]}" if second else first


def read(data_dir: Path) -> list[dict]:
    """Every competition-season in the directory, with its matches read."""
    competitions = json.loads((data_dir / "competitions.json").read_text(encoding="utf-8"))
    out = []
    for comp in competitions:
        path = data_dir / "matches" / str(comp["competition_id"]) / f"{comp['season_id']}.json"
        if not path.exists():
            continue
        matches = json.loads(path.read_text(encoding="utf-8"))
        results, missing, disagree = [], [], []
        for match in matches:
            mid = match["match_id"]
            ev, lu = data_dir / "events" / f"{mid}.json", data_dir / "lineups" / f"{mid}.json"
            if not ev.exists() or not lu.exists():
                missing.append(mid)
                continue
            result = aggregate.read_match(match, json.loads(ev.read_text(encoding="utf-8")),
                                          json.loads(lu.read_text(encoding="utf-8")))
            home, away = match["home_team"]["home_team_id"], match["away_team"]["away_team_id"]
            if (result.event_goals[home], result.event_goals[away]) != (match["home_score"], match["away_score"]):
                disagree.append((mid, match["home_score"], match["away_score"],
                                 result.event_goals[home], result.event_goals[away]))
            results.append((match, result))
        print(f"{comp['competition_name']} {comp['season_name']}: {len(results)} matches read, "
              f"{len(missing)} missing files, {len(disagree)} where event goals differ from the score",
              flush=True)
        for d in disagree[:5]:
            print(f"    match {d[0]}: score {d[1]}-{d[2]}, events {d[3]}-{d[4]}")
        out.append({"comp": comp, "results": results})
    return out


def _team_meta(seasons: list[dict], lineups_dir: Path) -> tuple[dict, dict]:
    """Team names and countries, and player names and nationalities, by StatsBomb id."""
    teams, people = {}, {}
    for s in seasons:
        international = bool(s["comp"].get("competition_international"))
        for match, _ in s["results"]:
            for side in ("home_team", "away_team"):
                t = match[side]
                tid = t[f"{side}_id"]
                country = (t.get("country") or {}).get("name", "")
                teams.setdefault(tid, {"name": t[f"{side}_name"], "country": country,
                                       "national": international})
            for team in json.loads((lineups_dir / f"{match['match_id']}.json").read_text(encoding="utf-8")):
                for p in team["lineup"]:
                    people.setdefault(p["player_id"], {
                        "name": p["player_name"], "nickname": p.get("player_nickname"),
                        "country": (p.get("country") or {}).get("name", ""),
                        "shirt": p.get("jersey_number"),
                    })
    return teams, people


def load(data_dir: Path, database_url: str) -> dict:
    seasons = read(data_dir)
    team_meta, people = _team_meta(seasons, data_dir / "lineups")
    modules = sports.registry()
    shot_type = modules["football"].events["shot"]
    unknown_countries: set[str] = set()

    engine = create_engine(database_url, future=True)
    with Session(engine) as db:
        db.execute(delete(MatchEvent).where(MatchEvent.source == SOURCE))
        db.execute(delete(PerformanceEntry).where(PerformanceEntry.source == SOURCE))
        db.execute(delete(TeamSeasonStat).where(TeamSeasonStat.source == SOURCE))

        # Teams.
        orgs: dict[int, Organization] = {}
        existing = {o.external_ids.get("statsbomb_team"): o for o in db.execute(
            select(Organization).where(Organization.external_ids.has_key("statsbomb_team"))).scalars()}
        for tid, meta in team_meta.items():
            code = iso_code(meta["country"])
            if code is None:
                unknown_countries.add(meta["country"])
            org = existing.get(tid) or Organization(id=uuid.uuid4(), external_ids={"statsbomb_team": tid})
            org.name = meta["name"]
            org.type = "national_team" if meta["national"] else "club"
            org.sport = "football"
            org.country = code or "ZZ"
            db.add(org)
            orgs[tid] = org
        db.flush()

        # Every match line, by player, team and season; dates per team and season.
        player_lines: dict[tuple, dict] = defaultdict(dict)
        team_lines: dict[tuple, dict] = defaultdict(dict)
        positions: dict[int, dict[str, float]] = defaultdict(dict)
        spans: dict[tuple, list[date]] = defaultdict(list)
        played_for: dict[tuple, list[date]] = defaultdict(list)
        all_shots, all_passes = [], []
        touch_lines: dict[tuple, list[int]] = {}
        for s in seasons:
            comp = s["comp"]
            key_c = (comp["competition_name"], comp["season_name"])
            players, teams, pos = aggregate.season_totals([r for _, r in s["results"]])
            for pid, by_team in players.items():
                for tid, counts in by_team.items():
                    aggregate.add(player_lines[(pid, tid, key_c)], counts)
            for tid, counts in teams.items():
                aggregate.add(team_lines[(tid, key_c)], counts)
            for pid, spent in pos.items():
                aggregate.add(positions[pid], spent)
            for pid, by_team in aggregate.season_touches([r for _, r in s["results"]]).items():
                for tid, grid in by_team.items():
                    touch_lines[(pid, tid, key_c)] = grid
            for match, result in s["results"]:
                day = date.fromisoformat(match["match_date"])
                for tid in result.teams:
                    spans[(tid, key_c)].append(day)
                for pid, tid in result.player_team.items():
                    played_for[(pid, tid)].append(day)
                label = (f"{match['home_team']['home_team_name']} {match['home_score']}-"
                         f"{match['away_score']} {match['away_team']['away_team_name']}")
                all_shots += [(shot, day, label) for shot in result.shots]
                all_passes += [(kp, day, label) for kp in result.key_passes]

        # Players.
        found = {p.external_ids.get("statsbomb"): p for p in db.execute(
            select(Player).where(Player.external_ids.has_key("statsbomb"))).scalars()}
        clubs_abroad = {pid for (pid, tid) in played_for if not team_meta[tid]["national"]}
        by_pid: dict[int, Player] = {}
        new_players = 0
        on_pitch = {k[0] for k in player_lines}
        for pid, meta in people.items():
            if pid not in on_pitch:
                continue  # in a squad, never on the pitch
            code = iso_code(meta["country"])
            if meta["country"] and code is None:
                unknown_countries.add(meta["country"])
            egyptian = code == EGYPT
            player = found.get(pid)
            if player is None:
                player = Player(id=uuid.uuid4(), external_ids={"statsbomb": pid}, status="active")
                new_players += 1
            player.full_name = meta["name"]
            player.known_as = meta["nickname"]
            player.nationality = [code] if code else []
            player.is_egypt_eligible = egyptian
            player.primary_sport = "football"
            player.sex = "male"
            player.date_of_birth = None
            # Senior professional competitions; the source gives no date of birth to say otherwise.
            player.is_minor = False
            player.tier = "diaspora" if egyptian and pid in clubs_abroad else "pro"
            player.position = aggregate.main_position(positions.get(pid, {}))
            db.add(player)
            by_pid[pid] = player
        db.flush()

        consented = {pid for (pid,) in db.execute(
            select(Consent.player_id).where(Consent.granted_by == GRANTED_BY)).all()}
        linked = {(a, b) for a, b in db.execute(
            select(PlayerOrganization.player_id, PlayerOrganization.organization_id)).all()}
        today = date.today()
        for player in by_pid.values():
            if player.id not in consented:
                for purpose in (ConsentPurpose.DATA_STORAGE, ConsentPurpose.ANALYTICS,
                                ConsentPurpose.SCOUTING_VISIBILITY):
                    db.add(Consent(id=uuid.uuid4(), player_id=player.id, purpose=purpose.value,
                                   granted=True, granted_by=GRANTED_BY, valid_from=today))
        for (pid, tid), days in played_for.items():
            if pid not in by_pid or (by_pid[pid].id, orgs[tid].id) in linked:
                continue
            db.add(PlayerOrganization(id=uuid.uuid4(), player_id=by_pid[pid].id,
                                      organization_id=orgs[tid].id, role="player",
                                      start_date=min(days), end_date=max(days),
                                      shirt_number=people[pid].get("shirt")))

        # Seasons.
        problems = 0
        for (pid, tid, (cname, sname)), counts in player_lines.items():
            if pid not in by_pid:
                continue
            days = spans[(tid, (cname, sname))]
            start, end = min(days), max(days)
            metrics = aggregate.player_season(counts)
            errors = sports.validate(metrics, SCHEMA_PLAYER, modules)
            if errors:
                problems += 1
                print(f"    invalid season for player {pid}: {errors}")
                continue
            db.add(PerformanceEntry(
                id=uuid.uuid4(), player_id=by_pid[pid].id, sport="football", period_type="season_aggregate",
                period_start=start, period_end=end, organization_id=orgs[tid].id,
                event=f"{cname} {season_label(sname)}", metrics=metrics, schema_ref=SCHEMA_PLAYER,
                source=SOURCE, is_validated=True,
            ))
        for (tid, (cname, sname)), counts in team_lines.items():
            days = spans[(tid, (cname, sname))]
            start, end = min(days), max(days)
            metrics = aggregate.team_season(counts)
            errors = sports.validate(metrics, SCHEMA_TEAM, modules)
            if errors:
                problems += 1
                print(f"    invalid team season for team {tid}: {errors}")
                continue
            db.add(TeamSeasonStat(organization_id=orgs[tid].id, sport="football", competition=cname,
                                  season=season_label(sname), period_start=start, period_end=end,
                                  schema_ref=SCHEMA_TEAM, metrics=metrics, source=SOURCE))
        for (pid, tid, (cname, sname)), grid in touch_lines.items():
            if pid not in by_pid or (pid, tid, (cname, sname)) not in player_lines:
                continue
            days = spans[(tid, (cname, sname))]
            metrics = aggregate.touch_map(grid)
            errors = sports.validate(metrics, SCHEMA_TOUCHES, modules)
            if errors:
                problems += 1
                continue
            db.add(PerformanceEntry(
                id=uuid.uuid4(), player_id=by_pid[pid].id, sport="football", period_type="season_touch_map",
                period_start=min(days), period_end=max(days), organization_id=orgs[tid].id,
                event=f"{cname} {season_label(sname)}", metrics=metrics, schema_ref=SCHEMA_TOUCHES,
                source=SOURCE, is_validated=True,
            ))

        # Shots.
        for shot, day, label in all_shots:
            if shot.player_id not in by_pid:
                continue
            details = {"situation": shot.situation, "xg": shot.xg}
            if shot.technique:
                details["technique"] = shot.technique
            if shot.placement:
                details["placement"] = shot.placement
            bad = shot_type.measures["xg"].problem(shot.xg)
            if bad:
                problems += 1
                continue
            db.add(MatchEvent(
                player_id=by_pid[shot.player_id].id, organization_id=orgs[shot.team_id].id,
                sport="football", match_date=day, match_label=label, event_type="shot",
                outcome=shot.outcome, x=shot.x, y=shot.y, video_seconds=None, details=details,
                source=SOURCE, tagged_by=None,
            ))
        # Key passes.
        pass_type = modules["football"].events["pass"]
        for kp, day, label in all_passes:
            if kp.player_id not in by_pid:
                continue
            measures = {"end_x": kp.end_x, "end_y": kp.end_y, "xa": kp.xa}
            if any(pass_type.measures[k].problem(v) for k, v in measures.items()):
                problems += 1
                continue
            db.add(MatchEvent(
                player_id=by_pid[kp.player_id].id, organization_id=orgs[kp.team_id].id,
                sport="football", match_date=day, match_label=label, event_type="pass",
                outcome=kp.outcome, x=kp.x, y=kp.y, video_seconds=None, details=measures,
                source=SOURCE, tagged_by=None,
            ))
        db.commit()

    return {
        "competitions": len(seasons),
        "players": len(by_pid), "new_players": new_players, "teams": len(orgs),
        "player_seasons": len(player_lines), "team_seasons": len(team_lines), "shots": len(all_shots),
        "key_passes": len(all_passes), "touch_maps": len(touch_lines),
        "problems": problems, "unknown_countries": sorted(unknown_countries),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    summary = load(args.data_dir, args.database_url)
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
