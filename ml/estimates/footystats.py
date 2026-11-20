"""Professional player seasons from a FootyStats cache (data/pipelines/footystats/fetch.py).

Reads the downloaded files directly, so the evaluation needs no database. The cache holds real
players' data and lives outside the repository; nothing it reads is ever written into it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

GROUPS = {"Goalkeeper": "goalkeeper", "Defender": "defender", "Midfielder": "midfielder", "Forward": "forward"}


@dataclass(frozen=True)
class PlayerSeason:
    player_id: int
    league: str
    season: str        # "2023/24"
    start_year: int    # 2023
    group: str         # goalkeeper, defender, midfielder, forward
    minutes: int
    np_goals: int      # goals minus penalty goals
    assists: int

    @property
    def exposure(self) -> float:
        """Minutes in 90-minute units."""
        return self.minutes / 90


def _known(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def load(cache_dir: Path, league: str) -> list[PlayerSeason]:
    """Every season in `league` with minutes played and the counts known; coaches left out."""
    manifest = json.loads((cache_dir / "manifest.json").read_text(encoding="utf-8"))
    out = []
    for season_id, info in manifest["seasons"].items():
        if info["league"] != league:
            continue
        rows = json.loads((cache_dir / season_id / "players.json").read_text(encoding="utf-8"))["data"]
        start_year = int(str(info["year"])[:4])
        for r in rows:
            group = GROUPS.get(r.get("position"))
            minutes, goals = r.get("minutes_played_overall"), r.get("goals_overall")
            pens, assists = r.get("penalty_goals"), r.get("assists_overall")
            if group is None or not all(_known(v) for v in (minutes, goals, pens, assists)) or minutes == 0:
                continue
            out.append(PlayerSeason(int(r["id"]), league, info["label"], start_year, group, minutes,
                                    max(0, goals - pens), assists))
    return out
