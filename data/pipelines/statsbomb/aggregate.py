"""StatsBomb open data, turned into the platform's own records. Pure functions, no database.

Decision 0008. One match is read from its three StatsBomb files (the match row from
`matches/<competition>/<season>.json`, `events/<match>.json` and `lineups/<match>.json`) and
turned into:

- **player match lines**: per player, the counts that make up `football.season_aggregate.v2`
  (minutes, goals, xG, passes, tackles and the rest). A season is the sum of its match lines.
- **team match lines**: per team, the counts that make up `football.team_season.v1`.
- **shots**: one per shot, for `match_event` (where it was taken, what happened, its xG).
- **key passes**: one per pass that led to a shot, for `match_event` (where it started and
  arrived, whether it was an assist, the xG of the shot it set up).
- **touches**: per player, how many of their events with a location fell in each zone of a
  12 by 8 grid over the pitch (`football.touch_map.v1`), for the heat map.

Every definition is written down here, because "a tackle" or "a duel" is a choice, and the same
choice must hold for every player. The penalty shootout (period 5) is not part of a match's
play and is left out of everything.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

SHOOTOUT = 5

# StatsBomb's 25 positions, as the platform's position codes (packages/shared/sports/football.json
# groups them). Wide midfielders are counted with wingers.
POSITIONS = {
    "Goalkeeper": "GK",
    "Right Back": "RB", "Right Wing Back": "RB",
    "Left Back": "LB", "Left Wing Back": "LB",
    "Right Center Back": "CB", "Center Back": "CB", "Left Center Back": "CB",
    "Right Defensive Midfield": "CDM", "Center Defensive Midfield": "CDM", "Left Defensive Midfield": "CDM",
    "Right Center Midfield": "CM", "Center Midfield": "CM", "Left Center Midfield": "CM",
    "Right Midfield": "RW", "Left Midfield": "LW",
    "Right Attacking Midfield": "CAM", "Center Attacking Midfield": "CAM", "Left Attacking Midfield": "CAM",
    "Right Wing": "RW", "Left Wing": "LW",
    "Right Center Forward": "ST", "Center Forward": "ST", "Left Center Forward": "ST",
    "Secondary Striker": "ST",
}

ON_TARGET = {"Goal", "Saved", "Saved to Post"}
BLOCKED = {"Blocked"}
TACKLE_WON = {"Won", "Success In Play", "Success Out"}
# Throw-ins are not counted as passes: they are restarts taken by hand.
NOT_A_PASS = {"Throw-in"}
SET_PIECE_SHOT = {"Penalty", "Free Kick", "Corner"}
SET_PIECE_PATTERN = {"From Corner", "From Free Kick"}

PLAYER_FIELDS = (
    "appearances", "starts", "minutes_played", "goals", "penalty_goals", "xg", "npxg", "assists", "xa",
    "shots", "shots_on_target", "key_passes", "passes_attempted", "passes_completed", "crosses",
    "dribbles_attempted", "dribbles_completed", "tackles", "interceptions", "duels", "duels_won",
    "aerial_duels", "aerial_duels_won", "clearances", "yellow_cards", "red_cards",
)
TEAM_FIELDS = (
    "matches", "wins", "draws", "losses", "points", "goals_for", "goals_against", "xg_for", "xg_against",
    "shots_for", "shots_against", "possession_seconds", "match_seconds", "clean_sheets", "home_points",
    "away_points", "goals_for_first_half", "goals_against_first_half", "goals_against_last_15",
    "set_piece_goals_for", "set_piece_goals_against",
)


@dataclass
class Shot:
    shot_id: str
    match_id: int
    player_id: int
    team_id: int
    period: int
    minute: int
    # On the platform's surface: 0 to 100 from the shooter's own goal line to the opponent's,
    # and 0 to 100 from left to right as the shooter faces the opponent's goal.
    x: float
    y: float
    outcome: str  # goal | on_target | off_target | blocked
    # The xG used everywhere (NorthStar's own model when the loader supplies it), and
    # StatsBomb's published value for the same shot, kept for comparison.
    xg: float
    technique: str | None
    situation: str
    placement: str | None
    xg_statsbomb: float = 0.0


@dataclass
class KeyPass:
    match_id: int
    player_id: int
    team_id: int
    # Platform units, as Shot: 0 to 100 along the pitch towards the opponent, left to right.
    x: float
    y: float
    end_x: float
    end_y: float
    outcome: str  # key_pass | assist
    xa: float


GRID_COLUMNS, GRID_ROWS = 12, 8


def zone(location: list) -> int:
    """The touch-map zone of a StatsBomb location (120 by 80): row by 10 across, column by 10 along."""
    column = min(GRID_COLUMNS - 1, max(0, int(location[0] // 10)))
    row = min(GRID_ROWS - 1, max(0, int(location[1] // 10)))
    return row * GRID_COLUMNS + column


@dataclass
class MatchResult:
    players: dict[int, dict] = field(default_factory=dict)  # player id -> counts
    player_team: dict[int, int] = field(default_factory=dict)
    player_position_seconds: dict[int, dict[str, float]] = field(default_factory=dict)
    teams: dict[int, dict] = field(default_factory=dict)  # team id -> counts
    shots: list[Shot] = field(default_factory=list)
    key_passes: list[KeyPass] = field(default_factory=list)
    # player id -> counts per zone, GRID_ROWS * GRID_COLUMNS of them, row by row.
    touches: dict[int, list[int]] = field(default_factory=dict)
    # Goals counted from the events, by team, to check against the published score.
    event_goals: dict[int, int] = field(default_factory=dict)


def _clock(text: str) -> int:
    """'47:12' -> seconds from kick-off on StatsBomb's running match clock."""
    minutes, seconds = text.split(":")
    return int(minutes) * 60 + int(seconds)


def _seconds(event: dict) -> int:
    return event["minute"] * 60 + event["second"]


def _zero(fields) -> dict:
    return {f: 0 for f in fields}


def _technique(shot: dict) -> str | None:
    if shot.get("body_part", {}).get("name") == "Head":
        return "header"
    name = shot.get("technique", {}).get("name")
    return {"Volley": "volley", "Half Volley": "volley", "Lob": "chip"}.get(name)


def _situation(shot: dict) -> str:
    kind = shot.get("type", {}).get("name")
    if kind == "Penalty":
        return "penalty"
    if kind in ("Free Kick", "Corner"):
        return "set_piece"
    return "open_play"


def _placement(shot: dict, outcome: str) -> str | None:
    """Where in the goal, seen from the shooter: thirds across the 8 yard mouth (y 36 to 44),
    halves of its height (z 0 to 2.67). Only for goals and saves with a height recorded."""
    end = shot.get("end_location") or []
    if outcome not in ("goal", "on_target") or len(end) < 3:
        return None
    y, z = end[1], end[2]
    column = "left" if y < 38.67 else "middle" if y < 41.33 else "right"
    return f"{'top' if z >= 1.33 else 'bottom'}_{column}"


def _outcome(name: str) -> str:
    if name == "Goal":
        return "goal"
    if name in ON_TARGET:
        return "on_target"
    if name in BLOCKED:
        return "blocked"
    return "off_target"


def _aerial_won(event: dict) -> bool:
    for key in ("pass", "shot", "clearance", "miscontrol"):
        if event.get(key, {}).get("aerial_won"):
            return True
    return False


def read_match(match: dict, events: list[dict], lineups: list[dict],
               xg: dict[str, float] | None = None) -> MatchResult:
    """Everything one match contributes. See the module docstring for the definitions.

    `xg` maps a shot's event id to the expected goals to use for it (NorthStar's own model,
    ml/xg); a shot not in it, or no map at all, uses StatsBomb's published value. Every xG
    figure below (players' xG, npxG and xA, teams' xG for and against, each shot's) follows it."""

    def shot_xg(shot_event: dict) -> float:
        own = xg.get(shot_event["id"]) if xg else None
        return float(own) if own is not None else float(shot_event["shot"].get("statsbomb_xg") or 0.0)

    out = MatchResult()
    home = match["home_team"]["home_team_id"]
    away = match["away_team"]["away_team_id"]
    in_play = [e for e in events if e.get("period", 0) != SHOOTOUT]
    end = max((_seconds(e) for e in in_play), default=0)

    # Minutes, starts and positions, from the lineups' time on the pitch in each position.
    for team in lineups:
        for player in team["lineup"]:
            pid = player["player_id"]
            on = 0.0
            started = False
            for spell in player.get("positions", []):
                if spell.get("from_period") == SHOOTOUT:
                    continue
                start = _clock(spell["from"])
                stop = _clock(spell["to"]) if spell.get("to") else end
                length = max(0, stop - start)
                on += length
                started = started or spell.get("start_reason") == "Starting XI"
                code = POSITIONS.get(spell.get("position", ""))
                if code:
                    spent = out.player_position_seconds.setdefault(pid, {})
                    spent[code] = spent.get(code, 0) + length
            if on <= 0:
                continue
            counts = out.players.setdefault(pid, _zero(PLAYER_FIELDS))
            counts["appearances"] = 1
            counts["starts"] = int(started)
            counts["minutes_played"] = round(on / 60)
            out.player_team[pid] = team["team_id"]

    def player(event: dict) -> dict | None:
        pid = (event.get("player") or {}).get("id")
        return out.players.get(pid) if pid is not None else None

    shots_by_id = {e["id"]: e for e in in_play if e["type"]["name"] == "Shot"}
    teams = {home: _zero(TEAM_FIELDS), away: _zero(TEAM_FIELDS)}
    out.event_goals = {home: 0, away: 0}
    other = {home: away, away: home}

    for e in in_play:
        kind = e["type"]["name"]
        p = player(e)
        team_id = (e.get("team") or {}).get("id")
        if p is not None and e.get("location"):
            grid = out.touches.setdefault(e["player"]["id"], [0] * (GRID_ROWS * GRID_COLUMNS))
            grid[zone(e["location"])] += 1
        if e.get("possession_team") and e.get("duration"):
            owner = e["possession_team"]["id"]
            if owner in teams:
                teams[owner]["possession_seconds"] += e["duration"]

        if kind == "Shot":
            s = e["shot"]
            outcome = _outcome(s["outcome"]["name"])
            value = shot_xg(e)
            penalty = s.get("type", {}).get("name") == "Penalty"
            goal = outcome == "goal"
            if p is not None:
                p["shots"] += 1
                p["shots_on_target"] += outcome in ("goal", "on_target")
                p["goals"] += goal
                p["penalty_goals"] += goal and penalty
                p["xg"] += value
                p["npxg"] += 0.0 if penalty else value
            if team_id in teams:
                t, against = teams[team_id], teams[other[team_id]]
                t["shots_for"] += 1
                against["shots_against"] += 1
                t["xg_for"] += value
                against["xg_against"] += value
                if goal:
                    out.event_goals[team_id] += 1
                    _goal(t, against, e, set_piece=_situation(s) != "open_play"
                          or e.get("play_pattern", {}).get("name") in SET_PIECE_PATTERN)
            loc = e.get("location") or [None, None]
            out.shots.append(Shot(
                shot_id=e["id"], match_id=match["match_id"], player_id=e["player"]["id"],
                team_id=team_id, period=e["period"], minute=e["minute"],
                x=round(loc[0] / 120 * 100, 1) if loc[0] is not None else None,
                y=round(loc[1] / 80 * 100, 1) if loc[1] is not None else None,
                outcome=outcome, xg=round(value, 4), technique=_technique(s), situation=_situation(s),
                placement=_placement(s, outcome),
                xg_statsbomb=round(float(s.get("statsbomb_xg") or 0.0), 4),
            ))
        elif kind == "Own Goal Against" and team_id in teams:
            # Credited to the other side: the team that put it in its own net conceded it.
            scorer = other[team_id]
            out.event_goals[scorer] += 1
            _goal(teams[scorer], teams[team_id], e, set_piece=False)
        elif p is None:
            continue
        elif kind == "Pass":
            q = e["pass"]
            if q.get("type", {}).get("name") in NOT_A_PASS:
                continue
            p["passes_attempted"] += 1
            p["passes_completed"] += "outcome" not in q
            p["crosses"] += bool(q.get("cross"))
            if q.get("goal_assist") or q.get("shot_assist"):
                p["key_passes"] += 1
            p["assists"] += bool(q.get("goal_assist"))
            assisted = shots_by_id.get(q.get("assisted_shot_id"))
            if assisted is not None:
                p["xa"] += shot_xg(assisted)
            if (q.get("goal_assist") or q.get("shot_assist")) and e.get("location") and q.get("end_location"):
                origin, target = e["location"], q["end_location"]
                out.key_passes.append(KeyPass(
                    match_id=match["match_id"], player_id=e["player"]["id"], team_id=team_id,
                    x=round(origin[0] / 120 * 100, 1), y=round(origin[1] / 80 * 100, 1),
                    end_x=round(min(target[0], 120) / 120 * 100, 1), end_y=round(min(max(target[1], 0), 80) / 80 * 100, 1),
                    outcome="assist" if q.get("goal_assist") else "key_pass",
                    xa=round(shot_xg(assisted), 4) if assisted is not None else 0.0,
                ))
        elif kind == "Dribble":
            p["dribbles_attempted"] += 1
            p["dribbles_completed"] += e["dribble"]["outcome"]["name"] == "Complete"
        elif kind == "Duel":
            duel = e.get("duel", {})
            if duel.get("type", {}).get("name") == "Tackle":
                p["tackles"] += 1
                won = duel.get("outcome", {}).get("name") in TACKLE_WON
                p["duels"] += 1
                p["duels_won"] += won
            elif duel.get("type", {}).get("name") == "Aerial Lost":
                p["aerial_duels"] += 1
                p["duels"] += 1
        elif kind == "Interception":
            p["interceptions"] += 1
        elif kind == "Clearance":
            p["clearances"] += 1
        if p is not None and kind in ("Foul Committed", "Bad Behaviour"):
            card = (e.get("foul_committed") or e.get("bad_behaviour") or {}).get("card", {}).get("name")
            if card == "Yellow Card":
                p["yellow_cards"] += 1
            elif card in ("Second Yellow", "Red Card"):
                p["red_cards"] += 1
        if p is not None and kind == "Dribble":
            # A take-on is a duel too, won when it comes off.
            p["duels"] += 1
            p["duels_won"] += e["dribble"]["outcome"]["name"] == "Complete"
        if p is not None and _aerial_won(e):
            p["aerial_duels"] += 1
            p["aerial_duels_won"] += 1
            p["duels"] += 1
            p["duels_won"] += 1

    # The result, from the published score (StatsBomb's own), so it is right even where the
    # events would disagree. load.py checks that they do not.
    hs, as_ = match["home_score"], match["away_score"]
    for team_id, scored, conceded, at_home in ((home, hs, as_, True), (away, as_, hs, False)):
        t = teams[team_id]
        t["matches"] = 1
        t["goals_for"], t["goals_against"] = scored, conceded
        win, draw = scored > conceded, scored == conceded
        t["wins"], t["draws"], t["losses"] = int(win), int(draw), int(not win and not draw)
        points = 3 if win else 1 if draw else 0
        t["points"] = points
        t["home_points" if at_home else "away_points"] = points
        t["clean_sheets"] = int(conceded == 0)
        t["match_seconds"] = end
    out.teams = teams
    return out


def _goal(scorer: dict, conceder: dict, event: dict, set_piece: bool) -> None:
    if event["period"] == 1:
        scorer["goals_for_first_half"] += 1
        conceder["goals_against_first_half"] += 1
    if event["period"] == 2 and event["minute"] >= 75:
        conceder["goals_against_last_15"] += 1
    if set_piece:
        scorer["set_piece_goals_for"] += 1
        conceder["set_piece_goals_against"] += 1


def add(total: dict, part: dict) -> None:
    for key, value in part.items():
        total[key] = total.get(key, 0) + value


def player_season(counts: dict) -> dict:
    """A season's summed match lines as `football.season_aggregate.v2` metrics."""
    out = {k: counts.get(k, 0) for k in PLAYER_FIELDS}
    for k in ("xg", "npxg", "xa"):
        out[k] = round(float(out[k]), 2)
    return out


def team_season(counts: dict) -> dict:
    """A season's summed team lines as `football.team_season.v1` metrics. Possession is the
    share of the in-play time that StatsBomb assigns to the team's possessions."""
    out = {k: counts.get(k, 0) for k in TEAM_FIELDS if k not in ("possession_seconds", "match_seconds")}
    own, theirs = counts.get("possession_seconds", 0.0), counts.get("possession_against_seconds", 0.0)
    share = own / (own + theirs) * 100 if own + theirs else 0.0
    out["possession_pct"] = round(share, 1)
    for k in ("xg_for", "xg_against"):
        out[k] = round(float(out[k]), 2)
    return out


def main_position(seconds: dict[str, float]) -> str | None:
    """The position a player spent most time in."""
    return max(seconds, key=seconds.get) if seconds else None


def touch_map(grid: list[int]) -> dict:
    """A summed grid as `football.touch_map.v1` metrics: z<row>_<col>, zones with none left out."""
    return {f"z{i // GRID_COLUMNS}_{i % GRID_COLUMNS}": n for i, n in enumerate(grid) if n}


def season_touches(results: list[MatchResult]) -> dict[int, dict[int, list[int]]]:
    """player id -> team id -> the season's summed touch grid."""
    out: dict[int, dict[int, list[int]]] = defaultdict(dict)
    for r in results:
        for pid, grid in r.touches.items():
            team = r.player_team.get(pid)
            if team is None:
                continue
            total = out[pid].setdefault(team, [0] * (GRID_ROWS * GRID_COLUMNS))
            for i, n in enumerate(grid):
                total[i] += n
    return out


def season_totals(results: list[MatchResult]) -> tuple[dict, dict, dict]:
    """Sum match lines into seasons. Returns (player id -> (team id -> counts)),
    (team id -> counts, with the opponents' possession for the share), and
    (player id -> position seconds)."""
    players: dict[int, dict[int, dict]] = defaultdict(dict)
    teams: dict[int, dict] = {}
    positions: dict[int, dict[str, float]] = defaultdict(dict)
    for r in results:
        for pid, counts in r.players.items():
            add(players[pid].setdefault(r.player_team[pid], {}), counts)
        ids = list(r.teams)
        for team_id, counts in r.teams.items():
            line = dict(counts)
            rival = next(t for t in ids if t != team_id)
            line["possession_against_seconds"] = r.teams[rival]["possession_seconds"]
            add(teams.setdefault(team_id, {}), line)
        for pid, spent in r.player_position_seconds.items():
            add(positions[pid], spent)
    return players, teams, positions
