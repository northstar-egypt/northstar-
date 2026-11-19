"""A small client for the FootyStats API (https://api.football-data-api.com).

Only the standard library, so the pipelines gain no dependency. It does three things the
endpoints need: it adds the key, it follows the pager across pages, and it retries when the
API is busy. The key is never printed, logged or put in an error message: everything that
leaves this module has it replaced by "***".

The API answers every call with {"success": ..., "pager": {...}, "data": [...]}. A call with
`success` false (a bad parameter, a season the key does not cover) raises FootyStatsError
with the API's own message.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

BASE_URL = "https://api.football-data-api.com"
# Seconds between calls. The test key's 1800 requests an hour are shared with everyone who uses
# it, so a full download (about 50 calls) is spread out rather than sent at once.
PAUSE = 1.0
RETRIES = 3
TIMEOUT = 60

# (url) -> (HTTP status, response body). Tests pass their own; the default goes to the network.
Transport = Callable[[str], tuple[int, bytes]]


class FootyStatsError(Exception):
    """The API refused a call, or answered with something that is not its usual JSON."""


def _urllib(url: str) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "northstar-pipeline"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class Client:
    def __init__(self, key: str, transport: Transport | None = None, pause: float = PAUSE,
                 retries: int = RETRIES, sleep: Callable[[float], None] = time.sleep):
        if not key:
            raise FootyStatsError("no FootyStats API key: set FOOTYSTATS_API_KEY in .env")
        self._key = key
        self._transport = transport or _urllib
        self._pause = pause
        self._retries = retries
        self._sleep = sleep
        self.calls = 0

    def redact(self, text: str) -> str:
        return text.replace(self._key, "***")

    def get(self, endpoint: str, **params) -> dict:
        """One call. Retries on 429 and 5xx with a growing wait; raises FootyStatsError otherwise."""
        query = urllib.parse.urlencode({"key": self._key, **params})
        url = f"{BASE_URL}/{endpoint}?{query}"
        for attempt in range(self._retries + 1):
            if self.calls:
                self._sleep(self._pause)
            self.calls += 1
            status, body = self._transport(url)
            if status == 429 or status >= 500:
                if attempt < self._retries:
                    self._sleep(self._pause * 2 ** (attempt + 2))
                    continue
                raise FootyStatsError(f"{endpoint}: HTTP {status} after {self._retries + 1} tries")
            if status != 200:
                raise FootyStatsError(f"{endpoint}: HTTP {status}: {self.redact(body[:200].decode('utf-8', 'replace'))}")
            try:
                payload = json.loads(body)
            except ValueError as exc:
                raise FootyStatsError(f"{endpoint}: the answer is not JSON") from exc
            if not isinstance(payload, dict) or not payload.get("success"):
                message = payload.get("message", "no message") if isinstance(payload, dict) else "not an object"
                raise FootyStatsError(f"{endpoint} {params}: refused: {self.redact(str(message))}")
            return payload
        raise AssertionError("unreachable")

    def all_pages(self, endpoint: str, **params) -> tuple[list, int]:
        """Every row across the pager's pages, and the total the API says it has."""
        first = self.get(endpoint, page=1, **params)
        pager = first.get("pager") or {}
        rows = list(first.get("data") or [])
        for page in range(2, int(pager.get("max_page") or 1) + 1):
            rows.extend(self.get(endpoint, page=page, **params).get("data") or [])
        total = int(pager.get("total_results", len(rows)))
        return rows, total
