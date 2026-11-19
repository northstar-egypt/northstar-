"""Download FootyStats seasons into a local cache, so nobody calls the API more than once.

    python -m data.pipelines.footystats.fetch --cache-dir D:/northstar-data/footystats

With no --season-id it downloads every season the key unlocks. The key comes from
FOOTYSTATS_API_KEY, or from the repository's .env when the variable is not set. FootyStats'
public test key unlocks the England Premier League 2018/19 to 2024/25 (and one Liga MX
season): the same format the Egyptian league arrives in, which is why the team develops on it.

What it writes, one folder per season, each file holding the API's rows untouched plus where
they came from (endpoint, parameters without the key, when, how many):

    <cache-dir>/leagues.json            the leagues and seasons the key unlocks
    <cache-dir>/manifest.json           what has been downloaded, and when
    <cache-dir>/<season_id>/players.json   league-players, every page
    <cache-dir>/<season_id>/matches.json   league-matches: team xG, shots, possession, odds
    <cache-dir>/<season_id>/teams.json     league-teams with their season statistics
    <cache-dir>/<season_id>/season.json    league-season: league-level statistics
    <cache-dir>/<season_id>/tables.json    league-tables: the standings

A season already in the cache is skipped unless --refresh is given, so an interrupted run can
simply be started again. The data is about real people: the cache folder must be outside the
repository, and the script refuses one inside it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from data.pipelines.footystats.client import Client, FootyStatsError

REPO = Path(__file__).resolve().parents[3]

# name -> (endpoint, extra parameters, whether the answer is a paged list)
KINDS: dict[str, tuple[str, dict, bool]] = {
    "players": ("league-players", {}, True),
    "matches": ("league-matches", {}, True),
    "teams": ("league-teams", {"include": "stats"}, True),
    "season": ("league-season", {}, False),
    "tables": ("league-tables", {}, False),
}


def season_label(year: int | str) -> str:
    """FootyStats writes 2024/25 as 20242025 and a calendar-year season as 2024."""
    text = str(year)
    if len(text) == 8:
        return f"{text[:4]}/{text[6:]}"
    return text


def check_outside_repo(cache_dir: Path) -> Path:
    resolved = cache_dir.resolve()
    if resolved == REPO or REPO in resolved.parents:
        raise SystemExit(
            f"refusing to cache FootyStats data inside the repository ({resolved}). It is data about "
            "real people and must never be committed; choose a folder outside it, for example "
            "D:/northstar-data/footystats.")
    return resolved


def key_from_env(var: str = "FOOTYSTATS_API_KEY", env_file: Path = REPO / ".env") -> str:
    if os.environ.get(var):
        return os.environ[var].strip()
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == var:
                return value.strip().strip('"').strip("'")
    return ""


def _write(path: Path, payload: dict) -> None:
    """Write through a temporary file, so a crash never leaves half a file that looks complete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def available_seasons(client: Client) -> list[dict]:
    """[{season_id, league, country, year, label}] for every season the key unlocks."""
    payload = client.get("league-list", chosen_leagues_only="true")
    out = []
    for league in payload.get("data") or []:
        for season in league.get("season") or []:
            out.append({"season_id": int(season["id"]), "league": league.get("name"),
                        "country": league.get("country"), "year": season.get("year"),
                        "label": season_label(season.get("year"))})
    return out


def fetch_kind(client: Client, season_id: int, kind: str) -> dict:
    endpoint, extra, paged = KINDS[kind]
    params = {"season_id": season_id, **extra}
    if paged:
        rows, total = client.all_pages(endpoint, **params)
        if len(rows) != total:
            raise FootyStatsError(f"{endpoint} season {season_id}: {len(rows)} rows read, the API reports {total}")
        data, count = rows, len(rows)
    else:
        data = client.get(endpoint, **params).get("data")
        count = 1 if data else 0
    return {"endpoint": endpoint, "params": params, "fetched_at": _now(), "rows": count, "data": data}


def fetch(client: Client, cache_dir: Path, season_ids: list[int] | None = None,
          refresh: bool = False, log=print) -> dict:
    """Download the seasons into cache_dir. Returns the manifest it wrote."""
    cache_dir = check_outside_repo(cache_dir)
    seasons = available_seasons(client)
    _write(cache_dir / "leagues.json", {"fetched_at": _now(), "seasons": seasons})
    by_id = {s["season_id"]: s for s in seasons}
    wanted = season_ids or list(by_id)
    unknown = [s for s in wanted if s not in by_id]
    if unknown:
        raise SystemExit(f"the key does not unlock season ids {unknown}; it unlocks {sorted(by_id)}")

    manifest_path = cache_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"seasons": {}}
    for season_id in wanted:
        info = by_id[season_id]
        entry = manifest["seasons"].setdefault(str(season_id), {**info, "files": {}})
        for kind in KINDS:
            path = cache_dir / str(season_id) / f"{kind}.json"
            if path.exists() and not refresh:
                log(f"  {info['league']} {info['label']} {kind}: already cached")
                continue
            payload = fetch_kind(client, season_id, kind)
            _write(path, payload)
            entry["files"][kind] = {"rows": payload["rows"], "fetched_at": payload["fetched_at"]}
            log(f"  {info['league']} {info['label']} {kind}: {payload['rows']} rows")
        _write(manifest_path, manifest)
    return manifest


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache-dir", required=True, type=Path, help="a folder outside the repository")
    parser.add_argument("--season-id", type=int, action="append", help="only this season; repeat for more")
    parser.add_argument("--refresh", action="store_true", help="download again even if cached")
    args = parser.parse_args(argv)
    check_outside_repo(args.cache_dir)
    client = Client(key_from_env())
    try:
        manifest = fetch(client, args.cache_dir, args.season_id, args.refresh)
    except FootyStatsError as exc:
        raise SystemExit(f"FootyStats: {exc}") from None
    print(f"\n{len(manifest['seasons'])} seasons in {args.cache_dir}, {client.calls} API calls this run.")


if __name__ == "__main__":
    main()
