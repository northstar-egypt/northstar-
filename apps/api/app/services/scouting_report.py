"""The pro scouting report for the web app, running `ml/pro/report.py` on the database.

The report is the ML module's; this file loads the rows, applies the profile's rules, and adds
what the screen draws beside it:

- finishing against expected goals over every season (ml/pro/sustainability.py) and the
  breakout detector's view of the graded season;
- the seasons on record, so the screen can switch between them (`competition`, `season`);
- three lines on what stands out, the weakest area and a caution, each read from the numbers
  of the report itself (`_case`), never written by a model;
- players whose season looks most alike (ml/pro/style.py), among players the caller may see;
- where data with locations exists (StatsBomb, decision 0008): the season's shots, its key
  passes, and a touch map for the heat map. The synthetic league has none, and says so.

- **Analytics consent**: a report is analytics on the player's data, so a player without it gets
  a note; and only players with it make up the populations a percentile is among.
- **Adults only**: ml/pro/report.py refuses a minor's report and says why.
- **Not to the player themselves**: a report is a scout's claim about a player, like the model
  flags the profile also keeps from a player's own view (there is no route to dispute one yet).
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import sports
from app.models.enums import ConsentPurpose
from app.models.match_event import MatchEvent
from app.models.organization import Organization
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.services import forecast  # noqa: F401  (puts ml/ on the path)
from app.services import gaps as gap_service
from app.services import pro as pro_service
from app.services.access import Caller, has_consent, may_view

from ml.pro import breakout, style, sustainability  # noqa: E402
from ml.pro import report as reports  # noqa: E402
from ml.pro.seasons import by_player, consecutive, first_years  # noqa: E402

TOUCH_MAP = "football.touch_map.v1"
SEASONS = "football.season_aggregate.v2"
GRID_ROWS, GRID_COLUMNS = 8, 12


def _finishing(f: sustainability.Finishing) -> dict:
    return {"npGoals": f.np_goals, "npxg": f.npxg, "low": f.low, "high": f.high,
            "verdict": f.verdict, "seasons": f.seasons}


def _ordinal(n: float) -> str:
    n = round(n)
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _case(spec, rep: reports.Report, finishing: sustainability.Finishing) -> list[dict]:
    """What stands out, the weakest area the role needs, and a caution, each from the report's
    own numbers. A line with nothing behind it is left out, never padded."""
    lines = []
    if rep.strengths:
        top = rep.strengths[:3]
        phrases = list(dict.fromkeys(spec.phrases.get(e.key, e.label.lower()) for e in top[:2]))
        lines.append({
            "kind": "strength",
            "headline": f"Stands out: {_join(phrases)}.",
            "detail": "; ".join(f"{e.label} {_ordinal(e.percentile)} percentile" for e in top) + ".",
        })
    graded = [a for a in rep.areas if a.graded and a.score is not None]
    weakest = min(graded, key=lambda a: a.score, default=None)
    if weakest is not None and weakest.score < 50:
        detail = "; ".join(f"{e.label} {_ordinal(e.percentile)} percentile" for e in weakest.evidence)
        lines.append({
            "kind": "weakness",
            "headline": f"{weakest.label} is the weakest area the role needs.",
            "detail": detail + ".",
        })
    if finishing.verdict == "above":
        lines.append({
            "kind": "caution",
            "headline": "Scoring above the chances.",
            "detail": f"{finishing.np_goals} non-penalty goals from {finishing.npxg} expected across all "
                      "seasons on record, above the range ordinary finishing gives: expect fewer.",
        })
    elif finishing.verdict == "below":
        lines.append({
            "kind": "caution",
            "headline": "Scoring below the chances.",
            "detail": f"{finishing.np_goals} non-penalty goals from {finishing.npxg} expected across all "
                      "seasons on record, below the usual range: the chances are there.",
        })
    if rep.confidence == "low":
        lines.append({
            "kind": "caution",
            "headline": "Few minutes behind this.",
            "detail": f"{rep.minutes} minutes in {rep.competition} {rep.season}: a low-confidence report.",
        })
    return lines


def _seasons(db: Session, mine: list, config, rep: reports.Report, min_minutes: int) -> list[dict]:
    clubs = {r.club for r in mine if r.club}
    names = dict(db.execute(select(Organization.id, Organization.name)
                            .where(Organization.id.in_([uuid.UUID(c) for c in clubs]))).all()) if clubs else {}
    out = []
    for r in sorted(mine, key=lambda r: (r.end, r.minutes), reverse=True):
        out.append({
            "competition": r.competition, "season": r.season, "minutes": r.minutes,
            "club": names.get(uuid.UUID(r.club)) if r.club else None,
            "gradable": config.group_of(r.position) is not None and r.minutes >= min_minutes,
            "selected": (r.competition, r.season) == (rep.competition, rep.season),
            "goals": int(r.metrics.get("goals", 0)), "assists": int(r.metrics.get("assists", 0)),
            "npxg": round(float(r.metrics.get("npxg", 0)), 2), "xa": round(float(r.metrics.get("xa", 0)), 2),
        })
    return out


def _similar(db: Session, caller: Caller, config, rows: list, row) -> list[dict]:
    found = style.similar(config, rows, row, shown=12)
    if not found:
        return []
    players = {str(p.id): p for p in db.execute(
        select(Player).where(Player.id.in_([uuid.UUID(m.player_id) for m in found]))).scalars()}
    clubs = dict(db.execute(select(Organization.id, Organization.name).where(
        Organization.id.in_([uuid.UUID(m.club) for m in found if m.club]))).all()) if found else {}
    out = []
    for m in found:
        p = players.get(m.player_id)
        if p is None or not may_view(db, caller, p)[0]:
            continue
        out.append({
            "playerId": m.player_id, "fullName": p.known_as or p.full_name, "competition": m.competition,
            "season": m.season, "club": clubs.get(uuid.UUID(m.club)) if m.club else None,
            "minutes": m.minutes, "similarity": round(m.similarity * 100),
        })
        if len(out) == style.SHOWN:
            break
    return out


def _on_the_pitch(db: Session, player: Player, rep: reports.Report, club: str | None) -> dict:
    """Shots, key passes and the touch map of the graded season, where the data has locations."""
    event = f"{rep.competition} {rep.season}"
    season = db.execute(select(PerformanceEntry).where(
        PerformanceEntry.player_id == player.id, PerformanceEntry.schema_ref == SEASONS,
        PerformanceEntry.event == event)).scalars().first()
    touches = db.execute(select(PerformanceEntry).where(
        PerformanceEntry.player_id == player.id, PerformanceEntry.schema_ref == TOUCH_MAP,
        PerformanceEntry.event == event)).scalars().first()
    events = []
    if season is not None:
        stmt = select(MatchEvent).where(
            MatchEvent.player_id == player.id, MatchEvent.match_date >= season.period_start,
            MatchEvent.match_date <= (season.period_end or season.period_start),
            MatchEvent.event_type.in_(["shot", "pass"]))
        if club:
            stmt = stmt.where(MatchEvent.organization_id == uuid.UUID(club))
        events = list(db.execute(stmt).scalars())
    shots = [{"x": e.x, "y": e.y, "outcome": e.outcome, "xg": (e.details or {}).get("xg"),
              "situation": (e.details or {}).get("situation")}
             for e in events if e.event_type == "shot" and e.x is not None]
    passes = [{"x": e.x, "y": e.y, "endX": (e.details or {}).get("end_x"), "endY": (e.details or {}).get("end_y"),
               "outcome": e.outcome, "xa": (e.details or {}).get("xa")}
              for e in events if e.event_type == "pass" and e.outcome in ("key_pass", "assist")
              and (e.details or {}).get("end_x") is not None]
    grid = None
    if touches is not None:
        grid = [int(touches.metrics.get(f"z{r}_{c}", 0)) for r in range(GRID_ROWS) for c in range(GRID_COLUMNS)]
    sources = {e.source for e in events} | ({touches.source} if touches is not None else set())
    # Shots that also carry StatsBomb's value were scored by NorthStar's own model (ml/xg).
    shot_details = [e.details or {} for e in events if e.event_type == "shot"]
    xg_model = ("northstar" if any("xg_statsbomb" in d for d in shot_details)
                else "statsbomb" if shot_details and "statsbomb" in sources else None)
    return {"shots": shots, "keyPasses": passes, "touchMap": grid,
            # Appearances in the season, not matches with a shot or key pass in them.
            "matches": int(season.metrics.get("appearances", 0)) if season is not None else 0,
            "eventSource": "statsbomb" if "statsbomb" in sources else (next(iter(sources)) if sources else None),
            "xgModel": xg_model}


def player_report(db: Session, caller: Caller, player: Player, competition: str | None = None,
                  season: str | None = None) -> dict:
    if caller.is_player:
        return {"report": None, "note": "Scouting reports are written for scouts and staff."}
    if not has_consent(db, player.id, ConsentPurpose.ANALYTICS.value):
        return {"report": None, "note": "Analytics consent is not in effect for this player, so no report is "
                                         "written about them."}
    module = sports.registry()["football"]
    if module.scouting_report is None:
        return {"report": None, "note": "This sport has no scouting report yet."}
    rows = gap_service._player_rows(db)
    try:
        # A player with no date of birth (StatsBomb's professionals) is graded when the platform
        # records them as an adult; and, unless one is asked for, the latest season that can be
        # graded is reported.
        rep = reports.build(module, rows, str(player.id),
                            known_adult=player.date_of_birth is None and not player.is_minor,
                            prefer_graded=True,
                            season=(competition, season) if competition and season else None)
    except reports.NoReport as reason:
        note = str(reason)
        if note == pro_service.NO_SEASONS:
            note = pro_service.no_seasons_note(db, player)
        return {"report": None, "note": note}

    mine = by_player(rows)[str(player.id)]
    # The season the report graded, which is not always the latest one (prefer_graded above).
    latest = max((r for r in mine if r.season == rep.season and r.competition == rep.competition),
                 key=lambda r: r.minutes)
    first_year = first_years(rows)
    assessed = None
    for previous, this in consecutive(mine, first_year):
        if this is latest:
            assessed = breakout.assess(previous, this, breakout.team_totals(
                [r for r in rows if r.club == latest.club]))
    club = db.execute(select(Organization.name).where(Organization.id == uuid.UUID(latest.club))).scalar_one_or_none() \
        if latest.club else None
    career = sustainability.career(mine)

    body = asdict(rep)
    body["club"] = club
    body["finishing"] = _finishing(career)
    body["breakout"] = ({"flagged": assessed.flagged, "reason": assessed.reason, "considered": assessed.score is not None}
                        if assessed else None)
    body["case"] = _case(module.scouting_report, rep, career)
    body["seasons"] = _seasons(db, mine, module.team_gaps, rep, reports.engine.MIN_MINUTES)
    body["similar"] = _similar(db, caller, module.team_gaps, rows, latest)
    body["pitch"] = _on_the_pitch(db, player, rep, latest.club)
    return {"report": body, "note": None}
