"""The pro page's managers box and "Learn from the pro" videos, from a hand-made list.

Parts 3 and 4 of "find the next <pro>" (ml/next_pro.py). Neither is analysis and neither is
part of the match score: they are context a coach or a young player reads on a professional's
page. Who coached the player and how, and official videos of the player giving advice or
telling their story.

Where the list lives
--------------------
These are facts about real people, and the repository never holds real player data, so the
list is a JSON file on your machine named by `PRO_EXTRAS_FILE` (format and a made-up example:
packages/shared/football/pro_extras.sample.json). With no file, or no entry for the player,
the page shows neither box. Nothing is ever filled in: a manager's style is what the person
who wrote the list wrote, and the box says it is hand-written.

Videos are embedded from youtube-nocookie.com by their id only, checked to be an id, so the
list cannot put arbitrary HTML or another site on the page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.config import get_settings
from app.models.player import Player

_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
NOTE = "Written by hand by the NorthStar team from public sources. Not part of any score."


def _load(path: str | None) -> dict:
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    players = data.get("players") if isinstance(data, dict) else None
    return players if isinstance(players, dict) else {}


def _text(value, limit: int = 300) -> str | None:
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def for_player(player: Player, path: str | None = None) -> dict:
    """The block for GET /players/{id}/pro-extras. Empty lists when there is nothing on file."""
    players = _load(path if path is not None else get_settings().pro_extras_file)
    keys = [f"player:{player.id}"]
    if (player.external_ids or {}).get("footystats") is not None:
        keys.insert(0, f"footystats:{player.external_ids['footystats']}")
    entry = next((players[k] for k in keys if isinstance(players.get(k), dict)), {})

    managers = []
    for m in entry.get("managers") or []:
        if isinstance(m, dict) and _text(m.get("name")):
            managers.append({"name": _text(m["name"], 80), "club": _text(m.get("club"), 80),
                             "years": _text(m.get("years"), 40), "style": _text(m.get("style"))})
    videos = []
    for v in entry.get("videos") or []:
        if isinstance(v, dict) and isinstance(v.get("youtube"), str) and _YOUTUBE_ID.match(v["youtube"]):
            videos.append({"title": _text(v.get("title"), 120) or "Video",
                           "youtube": v["youtube"], "kind": _text(v.get("kind"), 20)})
    return {"managers": managers, "videos": videos, "note": NOTE}
