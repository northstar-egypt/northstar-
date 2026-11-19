"""Load downloaded FootyStats seasons into the platform's database.

    python -m data.pipelines.footystats.load --cache-dir D:/northstar-data/footystats \\
        --database-url postgresql+psycopg://northstar:northstar@localhost:5432/northstar

The cache is what fetch.py downloaded. It holds real players' data and is kept outside the
repository; nothing from it is ever committed. With no --season-id every cached season loads.

What it writes, all with `source = 'footystats'`:

- organizations: one per club, found again by `external_ids.footystats_team`;
- players: one per FootyStats player, found again by `external_ids.footystats`, with their date
  of birth, nationality and clubs. FootyStats gives four position groups; only a goalkeeper
  maps to one of the platform's position codes, so outfield players keep no position rather
  than a guessed one. An Egyptian national playing in a league outside Egypt is the diaspora
  tier;
- `performance_entry` rows in `football.season_basic.v1`, one per player and season with minutes
  played (transform.py says what is in it, and why there is no xG or passing);
- `team_season_stat` rows in `football.team_season.v1`, one per team and season, computed from
  the season's matches and checked against FootyStats' own totals.

Nothing is invented to fill a gap: a row with a missing required field, or a team season whose
totals disagree with FootyStats', is not written, and the load report says which and why. The
report is printed and saved as `load_report.json` in the cache folder.

It can be run again: FootyStats rows are deleted and written afresh, and players and clubs are
matched by their FootyStats ids, so their platform ids (and anything pointing at them) stay.

Known limit: a player who is also in another source (StatsBomb) is a separate record; matching
people across sources is not built yet.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "apps" / "api"))

from sqlalchemy import create_engine, delete, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import sports  # noqa: E402
from app.models.consent import Consent  # noqa: E402
from app.models.enums import ConsentPurpose, PerformanceSource  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.performance_entry import PerformanceEntry  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.player_organization import PlayerOrganization  # noqa: E402
from app.models.team_season_stat import TeamSeasonStat  # noqa: E402
from data.pipelines.footystats import transform  # noqa: E402

SOURCE = PerformanceSource.FOOTYSTATS.value
SCHEMA_PLAYER = "football.season_basic.v1"
SCHEMA_TEAM = "football.team_season.v1"
GRANTED_BY = "footystats_api_terms"
EGYPT = "EG"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def cached_seasons(cache_dir: Path, season_ids: list[int] | None = None) -> list[dict]:
    """The manifest's seasons that are fully downloaded, with their files read."""
    manifest = json.loads((cache_dir / "manifest.json").read_text(encoding="utf-8"))
    out = []
    for sid, info in manifest["seasons"].items():
        if season_ids and int(sid) not in season_ids:
            continue
        folder = cache_dir / sid
        if not all((folder / f"{k}.json").exists() for k in ("players", "matches", "teams")):
            print(f"  {info['league']} {info['label']}: not fully downloaded, skipped")
            continue
        out.append({**info, "players": _read(folder / "players.json"), "matches": _read(folder / "matches.json"),
                    "teams": _read(folder / "teams.json")})
    return out


def _age(born: date, on: date) -> int:
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def load(cache_dir: Path, database_url: str, season_ids: list[int] | None = None) -> dict:
    seasons = cached_seasons(cache_dir, season_ids)
    modules = sports.registry()
    report: dict = {"loaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seasons": []}
    rejected_players: Counter = Counter()
    unknown_countries: Counter = Counter()

    engine = create_engine(database_url, future=True)
    with Session(engine) as db:
        db.execute(delete(PerformanceEntry).where(PerformanceEntry.source == SOURCE))
        db.execute(delete(TeamSeasonStat).where(TeamSeasonStat.source == SOURCE))

        # Clubs.
        existing_orgs = {o.external_ids.get("footystats_team"): o for o in db.execute(
            select(Organization).where(Organization.external_ids.has_key("footystats_team"))).scalars()}
        orgs: dict[int, Organization] = {}
        for s in seasons:
            for team in s["teams"]:
                org = existing_orgs.get(team["id"]) or orgs.get(team["id"]) or Organization(
                    id=uuid.uuid4(), external_ids={"footystats_team": team["id"]})
                org.name = team.get("cleanName") or team["name"]
                org.type = "club"
                org.sport = "football"
                org.country = transform.country_code(team.get("country") or s.get("country")) or "ZZ"
                db.add(org)
                orgs[team["id"]] = org
        db.flush()

        # Players: the latest season's details win; each season's line kept for later.
        latest: dict[int, tuple] = {}
        lines = []
        spells: dict[tuple[int, int], list[date]] = defaultdict(list)
        for s in seasons:
            span = transform.season_span(s["matches"])
            for row in s["players"]:
                metrics, why = transform.player_season(row)
                if metrics is None:
                    rejected_players[why] += 1
                    continue
                errors = sports.validate(metrics, SCHEMA_PLAYER, modules)
                if errors:
                    rejected_players[f"invalid: {errors[0]}"] += 1
                    continue
                pid = row["id"]
                if pid not in latest or s["year"] > latest[pid][0]["year"]:
                    latest[pid] = (s, row)
                lines.append((s, row, metrics, span))
                for club in (row.get("club_team_id"), row.get("club_team_2_id")):
                    if club and club > 0 and club in orgs and span:
                        spells[(pid, club)] += list(span)

        # The synthetic generator gives its players made-up FootyStats ids as text ("FS123456");
        # real ones are numbers, so only those are matched.
        found = {p.external_ids["footystats"]: p for p in db.execute(
            select(Player).where(Player.external_ids.has_key("footystats"))).scalars()
            if isinstance(p.external_ids["footystats"], int)}
        today = date.today()
        by_pid: dict[int, Player] = {}
        new_players = 0
        for pid, (s, row) in latest.items():
            player = found.get(pid)
            if player is None:
                player = Player(id=uuid.uuid4(), external_ids={"footystats": pid}, status="active")
                new_players += 1
            code = transform.country_code(row.get("nationality"))
            if row.get("nationality") and code is None:
                unknown_countries[row["nationality"]] += 1
            born = transform.day(row.get("birthday"))
            league_country = transform.country_code(s.get("country"))
            player.full_name = row.get("full_name") or row.get("known_as")
            player.known_as = row.get("known_as")
            player.date_of_birth = born
            player.is_minor = born is not None and _age(born, today) < 18
            player.nationality = [code] if code else []
            player.is_egypt_eligible = code == EGYPT
            player.primary_sport = "football"
            player.sex = "male"
            player.tier = "diaspora" if code == EGYPT and league_country != EGYPT else "pro"
            player.position = transform.POSITIONS.get(row.get("position"))
            db.add(player)
            by_pid[pid] = player
        db.flush()

        consented = {pid for (pid,) in db.execute(
            select(Consent.player_id).where(Consent.granted_by == GRANTED_BY)).all()}
        for player in by_pid.values():
            if player.id not in consented:
                for purpose in (ConsentPurpose.DATA_STORAGE, ConsentPurpose.ANALYTICS,
                                ConsentPurpose.SCOUTING_VISIBILITY):
                    db.add(Consent(id=uuid.uuid4(), player_id=player.id, purpose=purpose.value,
                                   granted=True, granted_by=GRANTED_BY, valid_from=today))

        links = {(lnk.player_id, lnk.organization_id): lnk for lnk in db.execute(select(PlayerOrganization)).scalars()}
        for (pid, club), days in spells.items():
            key = (by_pid[pid].id, orgs[club].id)
            link = links.get(key)
            if link is None:
                link = PlayerOrganization(id=uuid.uuid4(), player_id=key[0], organization_id=key[1], role="player")
                links[key] = link
            link.start_date = min([d for d in (link.start_date, min(days)) if d])
            link.end_date = max([d for d in (link.end_date, max(days)) if d])
            db.add(link)

        # Player seasons.
        for s, row, metrics, span in lines:
            start, end = span or (None, None)
            if start is None:
                rejected_players["season has no completed matches"] += 1
                continue
            club = row.get("club_team_id")
            db.add(PerformanceEntry(
                id=uuid.uuid4(), player_id=by_pid[row["id"]].id, sport="football", period_type="season_aggregate",
                period_start=start, period_end=end, organization_id=orgs[club].id if club in orgs else None,
                event=f"{s['league']} {s['label']}", metrics=metrics, schema_ref=SCHEMA_PLAYER,
                source=SOURCE, is_validated=True,
            ))

        # Team seasons.
        for s in seasons:
            span = transform.season_span(s["matches"])
            computed, match_problems = transform.team_seasons(s["matches"])
            stats = {t["id"]: t.get("stats") or {} for t in s["teams"]}
            entry = {"league": s["league"], "season": s["label"], "teams_written": 0,
                     "teams_rejected": {}, "match_problems": match_problems,
                     "player_seasons": sum(1 for x in lines if x[0] is s)}
            for team_id, metrics in computed.items():
                why = transform.reconcile(metrics, stats.get(team_id, {}))
                why += sports.validate(metrics, SCHEMA_TEAM, modules)
                if team_id not in orgs:
                    why.append("club not in the season's team list")
                if why or span is None:
                    entry["teams_rejected"][str(team_id)] = why or ["no completed matches"]
                    continue
                db.add(TeamSeasonStat(organization_id=orgs[team_id].id, sport="football",
                                      competition=s["league"], season=s["label"],
                                      period_start=span[0], period_end=span[1], schema_ref=SCHEMA_TEAM,
                                      metrics=metrics, source=SOURCE))
                entry["teams_written"] += 1
            report["seasons"].append(entry)
        db.commit()

    report.update({
        "players": len(by_pid), "new_players": new_players, "clubs": len(orgs),
        "player_seasons": len(lines), "player_rows_not_loaded": dict(rejected_players),
        "unknown_countries": dict(unknown_countries),
    })
    (cache_dir / "load_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--season-id", type=int, action="append", help="only this season; repeat for more")
    args = parser.parse_args(argv)
    print(json.dumps(load(args.cache_dir, args.database_url, args.season_id), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
