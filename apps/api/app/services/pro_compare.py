"""League seasons in the comparison view: professionals side by side on their basic seasons.

`GET /compare` puts two to four players side by side. For youth players that is their
measurements; a professional from FootyStats has none of those, only basic league seasons
(`football.season_basic.v1`: appearances, minutes, goals, assists, cards). This file adds those
seasons to the comparison, so two professionals can be compared on what their source publishes.
It holds no model of its own: the counts are counted, and the estimates are the talent-estimate
engine's (`app/services/estimates.py`, `ml/estimates`, graded in ml/README.md, "Talent
estimates"), exactly as the profile shows them. Tests: apps/api/tests/test_compare_seasons.py.

Which season
------------
Players are compared on one competition and season when they all have one in common (the most
recent such), because a rate means different things in different leagues and years. When they
have none in common, each player's most recent season is shown and the comparison says so.

What is shown, and what is not
------------------------------
- Counts as the source publishes them, summed over the clubs of one season (a mid-season move
  within a league is two rows, one season).
- Rates per 90 only from 450 minutes, the rule the app uses everywhere (radar, similarity, gap
  analysis): below that a rate is mostly chance, so it is left out and the row says why.
- The talent estimates, with their 80% range and the percentile among the player's league
  peers, only for players whose analytics consent is in effect (the estimates' own rule). When
  every player's range overlaps every other's, the row says the rates are not told apart
  rather than ranking them.
- A warning when the players are in different position groups: a forward's goals and a
  defender's are not the same thing.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.services import estimates

SCHEMA = estimates.SCHEMA
# Below this, a rate per 90 is left out: the platform's rule (radar, similarity, ml/pro/gaps.py).
RATE_MINUTES = 450

_COUNTS = ("appearances", "minutes_played", "goals", "assists", "penalty_goals",
           "yellow_cards", "red_cards", "clean_sheets", "goals_conceded")

# (key, label, unit, higher is better)
_ROWS = (
    ("appearances", "Appearances", "apps", True),
    ("minutes_played", "Minutes", "min", True),
    ("goals", "Goals", "goals", True),
    ("assists", "Assists", "assists", True),
    ("np_goals_per_90", "Non-penalty goals per 90", "per 90", True),
    ("assists_per_90", "Assists per 90", "per 90", True),
    ("yellow_cards", "Yellow cards", "cards", False),
    ("red_cards", "Red cards", "cards", False),
)
_ESTIMATED = (("np_goals", "Non-penalty goals per 90, estimated"), ("assists", "Assists per 90, estimated"))


def _season_label(event: str) -> str:
    return estimates._season_label(event)


def _competition(event: str) -> str:
    return event.rsplit(" ", 1)[0] if event else ""


def _seasons(db: Session, player: Player) -> dict[str, dict]:
    """The player's basic seasons by event, the counts summed over the season's clubs."""
    by_event: dict[str, dict] = {}
    minutes_by_group: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    rows = db.execute(select(PerformanceEntry).where(
        PerformanceEntry.player_id == player.id, PerformanceEntry.schema_ref == SCHEMA)).scalars()
    for entry in rows:
        if not entry.event:
            continue
        season = by_event.setdefault(entry.event, {
            "event": entry.event, "end": entry.period_end, "clubs": [], "metrics": dict.fromkeys(_COUNTS),
        })
        season["end"] = max(season["end"], entry.period_end)
        if entry.organization_id and entry.organization_id not in season["clubs"]:
            season["clubs"].append(entry.organization_id)
        for key in _COUNTS:
            value = entry.metrics.get(key)
            if value is not None:
                season["metrics"][key] = (season["metrics"][key] or 0) + value
        group = entry.metrics.get("position_group")
        if group:
            minutes_by_group[entry.event][group] += entry.metrics.get("minutes_played") or 0
    for event, season in by_event.items():
        groups = minutes_by_group.get(event)
        # The group the player spent most of the season in.
        season["position_group"] = max(groups, key=groups.get) if groups else None
    return by_event


def _choose(seasons: dict[str, dict[str, dict]]) -> tuple[dict[str, str | None], bool]:
    """Which event each player is compared on, and whether it is one event for all of them."""
    having = [s for s in seasons.values() if s]
    if having and len(having) == len(seasons):
        common = set.intersection(*(set(s) for s in having))
        if common:
            ends = {e: max(s[e]["end"] for s in having) for e in common}
            event = max(common, key=lambda e: (ends[e], e))
            return dict.fromkeys(seasons, event), True
    latest = {pid: (max(s, key=lambda e: (s[e]["end"], e)) if s else None) for pid, s in seasons.items()}
    return latest, False


def _rate(metrics: dict, numerator: str) -> float | None:
    minutes = metrics.get("minutes_played") or 0
    if minutes < RATE_MINUTES:
        return None
    if numerator == "np_goals":
        goals, pens = metrics.get("goals"), metrics.get("penalty_goals")
        if goals is None:
            return None
        count = goals - (pens or 0)
    else:
        count = metrics.get(numerator)
        if count is None:
            return None
    return count / (minutes / 90)


def _value(metrics: dict, key: str) -> float | None:
    if key == "np_goals_per_90":
        return _rate(metrics, "np_goals")
    if key == "assists_per_90":
        return _rate(metrics, "assists")
    value = metrics.get(key)
    return float(value) if value is not None else None


def _overlap(lows: list[float | None], highs: list[float | None]) -> bool:
    """True when at least two ranges are known and every pair of them overlaps."""
    known = [(lo, hi) for lo, hi in zip(lows, highs) if lo is not None and hi is not None]
    if len(known) < 2:
        return False
    return all(a_lo <= b_hi and b_lo <= a_hi for i, (a_lo, a_hi) in enumerate(known) for b_lo, b_hi in known[i + 1:])


def league_seasons(db: Session, players: list[Player]) -> dict | None:
    """The comparison's league-seasons section, or None when no player has a basic season."""
    seasons = {str(p.id): _seasons(db, p) for p in players}
    if not any(seasons.values()):
        return None
    chosen, same = _choose(seasons)

    club_ids = {c for pid, event in chosen.items() if event for c in seasons[pid][event]["clubs"]}
    names = dict(db.execute(select(Organization.id, Organization.name)
                            .where(Organization.id.in_(list(club_ids)))).all()) if club_ids else {}

    columns, picked = [], []
    for player in players:
        event = chosen[str(player.id)]
        season = seasons[str(player.id)].get(event) if event else None
        picked.append(season)
        if season is None:
            columns.append({"player_id": player.id, "competition": None, "season": None, "clubs": [],
                            "position_group": None, "note": "No league seasons on record."})
            continue
        columns.append({
            "player_id": player.id, "competition": _competition(event), "season": _season_label(event),
            "clubs": [names[c] for c in season["clubs"] if c in names],
            "position_group": season["position_group"], "note": None,
        })

    metrics = []
    for key, label, unit, higher in _ROWS:
        values = [(_value(s["metrics"], key) if s else None) for s in picked]
        note = None
        if key.endswith("_per_90") and any(
                s and (s["metrics"].get("minutes_played") or 0) < RATE_MINUTES for s in picked):
            note = f"Rates per 90 only from {RATE_MINUTES} minutes: below that they are mostly chance."
        metrics.append({"label": label, "unit": unit, "higher_is_better": higher, "values": values, "note": note})

    metrics.extend(_estimate_rows(db, players, chosen))

    caveats = []
    events = {e for e in chosen.values() if e}
    if not same and len(events) > 1:
        caveats.append("These players have no season in common, so each is shown on their most recent "
                       "one. A rate in one league or year is not the same as in another.")
    groups = {s["position_group"] for s in picked if s and s["position_group"]}
    if len(groups) > 1:
        caveats.append(f"Different position groups ({', '.join(sorted(groups))}): a forward's goals and "
                       f"a defender's are not the same thing.")
    return {
        "basis": "same season" if same else "most recent season each",
        "caveat": " ".join(caveats) or None,
        "players": columns,
        "metrics": metrics,
    }


def _estimate_rows(db: Session, players: list[Player], chosen: dict[str, str | None]) -> list[dict]:
    """The talent estimates for the chosen season, with their 80% range and percentile."""
    found: dict[str, dict] = {}
    notes: list[str] = []
    for player in players:
        event = chosen[str(player.id)]
        if not event:
            continue
        result = estimates.player_estimates(db, player)
        if result.get("note"):
            notes.append(f"{player.full_name}: {result['note']}")
            continue
        season = next((s for s in result["seasons"]
                       if s["competition"] == _competition(event) and s["season"] == _season_label(event)), None)
        if season is None:
            continue
        if season.get("note"):
            notes.append(f"{player.full_name}: {season['note']}")
        found[str(player.id)] = {m["key"]: m for m in season["measures"]}
    if not found:
        return []

    rows = []
    for key, label in _ESTIMATED:
        measures = [found.get(str(p.id), {}).get(key) for p in players]
        if not any(measures):
            continue
        lows = [m["low"] if m else None for m in measures]
        highs = [m["high"] if m else None for m in measures]
        apart = not _overlap(lows, highs)
        rows.append({
            "label": label, "unit": "per 90", "higher_is_better": True,
            "values": [m["estimate"] if m else None for m in measures],
            "lows": lows, "highs": highs,
            "percentiles": [m["percentile"] if m else None for m in measures],
            "indistinguishable": None if apart else True,
            "note": None if apart else "Their 80% ranges overlap, so these rates are not told apart.",
        })
    # Every estimate row says why a player has no estimate, since each row has the gap.
    for row in rows:
        if notes:
            row["note"] = " ".join(filter(None, [row["note"], *notes]))
    return rows
