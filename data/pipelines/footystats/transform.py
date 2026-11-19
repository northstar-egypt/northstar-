"""FootyStats rows as NorthStar records: pure functions, no database. load.py writes them.

- A player season becomes `football.season_basic.v1` metrics: only what FootyStats publishes
  for players (appearances, minutes, goals, assists, penalties, cards, clean sheets, goals
  conceded). Nothing is filled in: a field FootyStats marks unknown (-1) is left out, and a
  missing required field rejects the row with a reason.
- A team season becomes `football.team_season.v1` metrics, computed from the season's
  completed matches, then checked against FootyStats' own season totals for the team. A
  mismatch rejects the team season. Set piece goals are not published, so they are absent.

Every rejection comes back with a reason, for the load report.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone

from data.pipelines.statsbomb.countries import iso_code

# FootyStats' spellings that differ from the names countries.py knows.
COUNTRY_ALIASES = {
    "Republic of Ireland": "Ireland", "Northern Ireland": "England", "Scotland": "England",
    "Wales": "England", "Ivory Coast": "Cote d'Ivoire", "DR Congo": "Congo, (Kinshasa)",
    "Congo DR": "Congo, (Kinshasa)", "Iran": "Iran, Islamic Republic of", "Czechia": "Czech Republic",
    "Turkiye": "Turkey", "Cabo Verde": "Cape Verde",
}
# Countries countries.py does not cover (it lists the StatsBomb competitions' countries).
EXTRA_CODES = {
    "USA": "US", "United States": "US", "South Korea": "KR", "Korea Republic": "KR", "Venezuela": "VE",
    "Israel": "IL", "Estonia": "EE", "Grenada": "GD", "Bolivia": "BO", "Uzbekistan": "UZ",
    "Philippines": "PH", "Cuba": "CU", "Tanzania": "TZ", "Guatemala": "GT", "Honduras": "HN",
    "FYR Macedonia": "MK", "North Macedonia": "MK", "St. Kitts and Nevis": "KN", "Montserrat": "MS",
}

# FootyStats' four position groups. Only a goalkeeper maps to one of the platform's position
# codes; "Defender" could be a centre back or a full back, so outfield players keep no code
# rather than a guessed one.
POSITIONS = {"Goalkeeper": "GK"}
NOT_PLAYERS = {"Coach"}


def country_code(name: str | None) -> str | None:
    if not name:
        return None
    return EXTRA_CODES.get(name) or iso_code(COUNTRY_ALIASES.get(name, name))


def day(unix: int | None) -> date | None:
    """A FootyStats timestamp (seconds, UTC) as a date; None for missing (0 or -1)."""
    if not unix or unix < 0:
        return None
    return datetime.fromtimestamp(unix, tz=timezone.utc).date()


def season_label(name: str) -> str:
    """'2024/2025' as '2024/25', the platform's form; a calendar year stays as it is."""
    first, sep, second = str(name).partition("/")
    return f"{first}/{second[-2:]}" if sep else first


def _known(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


PLAYER_FIELDS = {
    # NorthStar metric: FootyStats field
    "appearances": "appearances_overall",
    "minutes_played": "minutes_played_overall",
    "goals": "goals_overall",
    "assists": "assists_overall",
    "penalty_goals": "penalty_goals",
    "penalty_misses": "penalty_misses",
    "yellow_cards": "yellow_cards_overall",
    "red_cards": "red_cards_overall",
    "clean_sheets": "clean_sheets_overall",
    "goals_conceded": "conceded_overall",
}
PLAYER_REQUIRED = ("appearances", "minutes_played", "goals", "assists", "yellow_cards", "red_cards")


def player_season(row: dict) -> tuple[dict | None, str | None]:
    """(metrics, None) for a season to store, or (None, why not)."""
    if row.get("position") in NOT_PLAYERS:
        return None, "not a player (coach)"
    metrics = {}
    for ours, theirs in PLAYER_FIELDS.items():
        value = row.get(theirs)
        if _known(value):
            metrics[ours] = int(value)
    missing = [k for k in PLAYER_REQUIRED if k not in metrics]
    if missing:
        return None, f"missing {', '.join(missing)}"
    if metrics["minutes_played"] == 0:
        return None, "never played (0 minutes)"
    return metrics, None


def _minute(stamp) -> int:
    """'87' -> 87, '45+2' -> 45, '90+4' -> 90: the minute of the half the goal is credited to."""
    return int(str(stamp).split("+")[0].split("'")[0])


def _first_half(stamp) -> bool:
    """'45+2' is first-half stoppage time; '90+2' and '46' are not."""
    text = str(stamp)
    return text.startswith("45+") or ("+" not in text and _minute(text) <= 45)


TEAM_FIELDS = ("matches", "wins", "draws", "losses", "points", "goals_for", "goals_against", "xg_for",
               "xg_against", "shots_for", "shots_against", "possession_pct", "clean_sheets", "home_points",
               "away_points", "goals_for_first_half", "goals_against_first_half", "goals_against_last_15")
MATCH_NUMBERS = ("team_a_xg", "team_b_xg", "team_a_shots", "team_b_shots", "team_a_possession", "team_b_possession")


def team_seasons(matches: list[dict]) -> tuple[dict[int, dict], list[str]]:
    """team id -> team_season.v1 metrics from the completed matches, and the matches set aside.

    A completed match missing xG, shots or possession would make every total wrong, so it
    rejects both teams' seasons (reported), rather than being skipped."""
    rows: dict[int, dict] = defaultdict(lambda: {k: 0 for k in TEAM_FIELDS})
    possession: dict[int, list[float]] = defaultdict(list)
    broken_teams: set[int] = set()
    problems = []
    for m in matches:
        if m.get("status") != "complete":
            continue
        home, away = m["homeID"], m["awayID"]
        if not all(_known(m.get(k)) for k in MATCH_NUMBERS):
            broken_teams |= {home, away}
            problems.append(f"match {m.get('id')}: xG, shots or possession missing")
            continue
        hg, ag = int(m["homeGoalCount"]), int(m["awayGoalCount"])
        sides = ((home, "a", hg, ag, m["homeGoals_timings"], m["awayGoals_timings"], "home_points"),
                 (away, "b", ag, hg, m["awayGoals_timings"], m["homeGoals_timings"], "away_points"))
        for team, me, scored, conceded, mine, theirs, where in sides:
            them = "b" if me == "a" else "a"
            r = rows[team]
            points = 3 if scored > conceded else 1 if scored == conceded else 0
            r["matches"] += 1
            r["wins"] += scored > conceded
            r["draws"] += scored == conceded
            r["losses"] += scored < conceded
            r["points"] += points
            r[where] += points
            r["goals_for"] += scored
            r["goals_against"] += conceded
            r["xg_for"] += float(m[f"team_{me}_xg"])
            r["xg_against"] += float(m[f"team_{them}_xg"])
            r["shots_for"] += int(m[f"team_{me}_shots"])
            r["shots_against"] += int(m[f"team_{them}_shots"])
            r["clean_sheets"] += conceded == 0
            r["goals_for_first_half"] += sum(1 for g in mine if _first_half(g))
            r["goals_against_first_half"] += sum(1 for g in theirs if _first_half(g))
            r["goals_against_last_15"] += sum(1 for g in theirs if _minute(g) >= 76)
            possession[team].append(float(m[f"team_{me}_possession"]))
    out = {}
    for team, r in rows.items():
        if team in broken_teams:
            continue
        r["xg_for"] = round(r["xg_for"], 2)
        r["xg_against"] = round(r["xg_against"], 2)
        r["possession_pct"] = round(sum(possession[team]) / len(possession[team]), 1)
        out[team] = dict(r)
    return out, problems


# NorthStar team metric: FootyStats' own season total for the team (league-teams stats).
RECONCILE = {
    "matches": "seasonMatchesPlayed_overall", "wins": "seasonWinsNum_overall",
    "draws": "seasonDrawsNum_overall", "losses": "seasonLossesNum_overall",
    "goals_for": "seasonGoals_overall", "goals_against": "seasonConceded_overall",
    "clean_sheets": "seasonCS_overall",
}


def reconcile(ours: dict, stats: dict) -> list[str]:
    """Where the totals computed from matches disagree with FootyStats' own; empty when they agree."""
    out = []
    for key, theirs in RECONCILE.items():
        if theirs in stats and _known(stats[theirs]) and int(stats[theirs]) != ours[key]:
            out.append(f"{key}: {ours[key]} from matches, {stats[theirs]} in FootyStats' totals")
    return out


def season_span(matches: list[dict]) -> tuple[date, date] | None:
    days = [d for m in matches if m.get("status") == "complete" for d in [day(m.get("date_unix"))] if d]
    return (min(days), max(days)) if days else None
