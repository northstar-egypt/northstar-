"""data/pipelines/footystats: the client and the cache, against a fake API (no network).

Everything the fake API returns is invented: no real player, team or match appears here.
"""

from __future__ import annotations

import json
import urllib.parse

import pytest

from data.pipelines.footystats import fetch
from data.pipelines.footystats.client import Client, FootyStatsError

KEY = "invented-test-key-123"


def _ok(data, page=1, max_page=1, total=None):
    rows = data if isinstance(data, list) else [data]
    return {"success": True, "pager": {"current_page": page, "max_page": max_page,
                                       "total_results": len(rows) if total is None else total},
            "data": data}


class FakeApi:
    """Answers by endpoint and page; records every URL it was called with."""

    def __init__(self, players_pages=2, refuse=None, busy=0):
        self.urls: list[str] = []
        self.players_pages = players_pages
        self.refuse = refuse or set()
        self.busy = busy

    def __call__(self, url: str):
        self.urls.append(url)
        if self.busy:
            self.busy -= 1
            return 429, b"slow down"
        parsed = urllib.parse.urlparse(url)
        endpoint = parsed.path.strip("/")
        q = dict(urllib.parse.parse_qsl(parsed.query))
        if endpoint in self.refuse:
            return 200, json.dumps({"success": False, "message": f"bad key {q['key']}"}).encode()
        page = int(q.get("page", 1))
        if endpoint == "league-list":
            body = _ok([{"name": "Invented League", "country": "Nowhere",
                         "season": [{"id": 11, "year": 20292030}, {"id": 12, "year": 2031}]}])
        elif endpoint == "league-players":
            n = self.players_pages
            body = _ok([{"id": page * 10 + i, "full_name": f"Invented Player {page}-{i}"} for i in range(3)],
                       page=page, max_page=n, total=3 * n)
        elif endpoint == "league-matches":
            body = _ok([{"id": 1, "homeID": 1, "awayID": 2, "team_a_xg": 1.2}])
        elif endpoint == "league-teams":
            assert q.get("include") == "stats"
            body = _ok([{"id": 1, "stats": {"xg_for_avg_overall": 1.1}}, {"id": 2, "stats": {}}])
        elif endpoint in ("league-season", "league-tables"):
            body = _ok({"id": int(q["season_id"])})
        else:
            return 404, b"not found"
        return 200, json.dumps(body).encode()


def _client(api, **kw):
    return Client(KEY, transport=api, pause=0, sleep=lambda s: None, **kw)


@pytest.fixture
def cache(tmp_path):
    return tmp_path / "footystats"


def test_downloads_every_kind_and_every_page(cache):
    api = FakeApi(players_pages=3)
    manifest = fetch.fetch(_client(api), cache, season_ids=[11], log=lambda m: None)
    players = json.loads((cache / "11" / "players.json").read_text(encoding="utf-8"))
    assert players["rows"] == 9 and len(players["data"]) == 9
    assert players["endpoint"] == "league-players" and players["params"] == {"season_id": 11}
    for kind in fetch.KINDS:
        assert (cache / "11" / f"{kind}.json").exists()
    assert manifest["seasons"]["11"]["label"] == "2029/30"
    assert set(manifest["seasons"]["11"]["files"]) == set(fetch.KINDS)
    assert not (cache / "12").exists()


def test_all_seasons_when_none_given(cache):
    fetch.fetch(_client(FakeApi()), cache, log=lambda m: None)
    assert (cache / "11" / "players.json").exists() and (cache / "12" / "players.json").exists()


def test_cached_files_are_not_downloaded_again(cache):
    fetch.fetch(_client(FakeApi()), cache, season_ids=[11], log=lambda m: None)
    again = FakeApi()
    fetch.fetch(_client(again), cache, season_ids=[11], log=lambda m: None)
    assert [u for u in again.urls if "league-list" not in u] == []
    refreshed = FakeApi()
    fetch.fetch(_client(refreshed), cache, season_ids=[11], refresh=True, log=lambda m: None)
    assert any("league-players" in u for u in refreshed.urls)


def test_the_key_never_reaches_disk_or_errors(cache):
    fetch.fetch(_client(FakeApi()), cache, season_ids=[11], log=lambda m: None)
    for path in cache.rglob("*.json"):
        assert KEY not in path.read_text(encoding="utf-8")
    with pytest.raises(FootyStatsError) as err:
        _client(FakeApi(refuse={"league-players"})).get("league-players", season_id=11)
    assert KEY not in str(err.value) and "***" in str(err.value)


def test_a_refused_call_leaves_no_file(cache):
    with pytest.raises(FootyStatsError):
        fetch.fetch(_client(FakeApi(refuse={"league-matches"})), cache, season_ids=[11], log=lambda m: None)
    assert (cache / "11" / "players.json").exists()
    assert not (cache / "11" / "matches.json").exists()
    assert not list(cache.rglob("*.tmp"))


def test_busy_api_is_retried():
    api = FakeApi(busy=2)
    assert _client(api).get("league-matches", season_id=11)["success"]
    assert len(api.urls) == 3
    with pytest.raises(FootyStatsError, match="HTTP 429"):
        _client(FakeApi(busy=5), retries=2).get("league-matches", season_id=11)


def test_a_short_download_is_an_error(cache):
    class Short(FakeApi):
        def __call__(self, url):
            status, body = super().__call__(url)
            payload = json.loads(body)
            if "league-players" in url:
                payload["pager"]["total_results"] = 99
            return status, json.dumps(payload).encode()

    with pytest.raises(FootyStatsError, match="the API reports 99"):
        fetch.fetch(_client(Short()), cache, season_ids=[11], log=lambda m: None)


def test_unknown_season_is_refused(cache):
    with pytest.raises(SystemExit, match="does not unlock"):
        fetch.fetch(_client(FakeApi()), cache, season_ids=[99], log=lambda m: None)


def test_cache_inside_the_repository_is_refused():
    with pytest.raises(SystemExit, match="inside the repository"):
        fetch.check_outside_repo(fetch.REPO / "data" / "footystats-cache")


def test_no_key_is_a_clear_error():
    with pytest.raises(FootyStatsError, match="FOOTYSTATS_API_KEY"):
        Client("")


def test_key_read_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("FOOTYSTATS_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nFOOTYSTATS_API_KEY=abc123\n", encoding="utf-8")
    assert fetch.key_from_env(env_file=env) == "abc123"
    monkeypatch.setenv("FOOTYSTATS_API_KEY", "from-env")
    assert fetch.key_from_env(env_file=env) == "from-env"


def test_season_labels():
    assert fetch.season_label(20242025) == "2024/25"
    assert fetch.season_label("2024") == "2024"
