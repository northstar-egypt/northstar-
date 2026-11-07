"""The pro scouting report for the web app, running `ml/pro/report.py` on the database.

The report is the ML module's; this file loads the rows, applies the profile's rules, and adds
two pieces of evidence the pro tier already measures: finishing against expected goals over
every season (ml/pro/sustainability.py) and the breakout detector's view of the latest season.

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
from app.models.organization import Organization
from app.models.player import Player
from app.services import forecast  # noqa: F401  (puts ml/ on the path)
from app.services import gaps as gap_service
from app.services.access import Caller, has_consent

from ml.pro import breakout, sustainability  # noqa: E402
from ml.pro import report as reports  # noqa: E402
from ml.pro.seasons import by_player, consecutive  # noqa: E402


def _finishing(f: sustainability.Finishing) -> dict:
    return {"npGoals": f.np_goals, "npxg": f.npxg, "low": f.low, "high": f.high,
            "verdict": f.verdict, "seasons": f.seasons}


def player_report(db: Session, caller: Caller, player: Player) -> dict:
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
        rep = reports.build(module, rows, str(player.id))
    except reports.NoReport as reason:
        return {"report": None, "note": str(reason)}

    mine = by_player(rows)[str(player.id)]
    latest = max(mine, key=lambda r: (r.end, r.minutes))
    first_year = min(r.end.year for r in rows)
    assessed = None
    for previous, this in consecutive(mine, first_year):
        if this is latest:
            assessed = breakout.assess(previous, this, breakout.team_totals(
                [r for r in rows if r.club == latest.club]))
    club = db.execute(select(Organization.name).where(Organization.id == uuid.UUID(latest.club))).scalar_one_or_none() \
        if latest.club else None

    body = asdict(rep)
    body["club"] = club
    body["finishing"] = _finishing(sustainability.career(mine))
    body["breakout"] = ({"flagged": assessed.flagged, "reason": assessed.reason, "considered": assessed.score is not None}
                        if assessed else None)
    return {"report": body, "note": None}
