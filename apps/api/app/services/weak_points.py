"""Improve weak points: a youth player's weakest match statistics, drills for them, and how
each has moved season by season. Part 5 of "find the next <pro>" (ml/next_pro.py).

No new analysis. The weak points are the radar's percentiles (app/services/radar.py: same sport,
gender, kind of position and age, only players with analytics consent, no percentile from too
few players), so the two screens never disagree.

- **A weak point** is a statistic that matters for the player's kind of position
  (the sport module, `weakPoints.matters` in packages/shared/sports/football.json) with a percentile below `WEAK_BELOW`. At
  most `SHOWN`, weakest first. A statistic with no percentile is never called weak.
- **Drills** come from the same place: built-in starter drills written by the team. Coaches
  adding their own needs a table and is future work.
- **Progress** is the player's own rate for each weak statistic in each season (August to
  July) with at least `SEASON_MIN_MINUTES` minutes, as plain numbers. No percentile per season:
  a season's comparison group would often be too small to mean anything.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.services import radar
from app.sports import default_modules_dir

WEAK_BELOW = 40
SHOWN = 3
SEASON_MIN_MINUTES = 270
SCHEMA = "football.match.v1"


@lru_cache(maxsize=1)
def _drills() -> dict:
    path = default_modules_dir() / "football.json"
    return json.loads(path.read_text(encoding="utf-8"))["weakPoints"]


def _season(day: date) -> str:
    start = day.year if day.month >= 8 else day.year - 1
    return f"{start}/{str(start + 1)[-2:]}"


def _progress(db: Session, player: Player, keys: list[str]) -> list[dict]:
    totals: dict[str, dict[str, float]] = {}
    for start, metrics in db.execute(
        select(PerformanceEntry.period_start, PerformanceEntry.metrics)
        .where(PerformanceEntry.player_id == player.id, PerformanceEntry.schema_ref == SCHEMA)
    ).all():
        if start is None:
            continue
        t = totals.setdefault(_season(start), {})
        for k, v in (metrics or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                t[k] = t.get(k, 0) + v
    out = []
    for season in sorted(totals):
        t = totals[season]
        minutes = t.get("minutes_played", 0)
        if minutes < SEASON_MIN_MINUTES:
            continue
        values = {}
        for k in keys:
            if k == "pass_completion":
                if t.get("passes_attempted"):
                    values[k] = round(t.get("passes_completed", 0) / t["passes_attempted"] * 100, 1)
            elif k in t:
                values[k] = round(t[k] / minutes * 90, 2)
        out.append({"season": season, "minutes": int(minutes), "values": values})
    return out


def weak_points(db: Session, player: Player) -> dict:
    """The block for GET /players/{id}/weak-points."""
    if player.primary_sport != "football":
        return {"items": [], "progress": [], "population": None,
                "note": "Weak points are for football players for now."}
    r = radar.player_radar(db, player)
    if not r["axes"]:
        return {"items": [], "progress": [], "population": None, "note": r["note"]}
    role = radar._role("football", player.position)
    matters = set(_drills()["matters"].get(role or "", []))
    weak = sorted(
        (a for a in r["axes"] if a["key"] in matters and a["percentile"] is not None
         and a["percentile"] < WEAK_BELOW),
        key=lambda a: a["percentile"],
    )[:SHOWN]
    if not weak:
        return {"items": [], "progress": [], "population": r["population"], "note": (
            f"No clear weak point: every statistic that matters for the position is at or above "
            f"the {WEAK_BELOW}th percentile, or has too few players to compare with.")}
    drills = _drills()["drills"]
    items = [{"key": a["key"], "label": a["label"], "value": a["value"], "unit": a["unit"],
              "percentile": a["percentile"], "drills": drills.get(a["key"], [])} for a in weak]
    return {
        "items": items,
        "progress": _progress(db, player, [a["key"] for a in weak]),
        "population": r["population"],
        "note": (f"Weak points are statistics that matter for the position where the player is "
                 f"below the {WEAK_BELOW}th percentile of the players named above, the same "
                 "comparison as the radar. Drills are built-in starting points; a coach knows "
                 "the player best."),
    }
