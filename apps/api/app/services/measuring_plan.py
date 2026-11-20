"""The coach's measuring plan: whom to measure today, and why.

The optimiser is ml/decisions/measurement.py, the one graded in ml/README.md, "Who to measure
next": against the squad screen's old order (longest since the last reading first) it flagged
more of the late bloomers a size cut would release, for the same number of readings, and it
halved the share who reached that moment with too few readings. This file only gathers the
squad and applies it.

- The squad is the coach's own (`visible_players`), players whose analytics consent is in
  effect: the late-bloomer check does not run on the others, so measuring them for it would be
  asking for data the platform will not use. They are counted, not planned.
- How many the coach can measure today is the coach's to say. The suggestion is enough for
  everyone to be measured about every SUGGESTED_EVERY_DAYS days, the backtest's advice.
- A height's size for age is a z-score among every player with analytics consent measured in
  the last six months, the same reference the evaluation used.
- Every player chosen comes with the reasons, in plain words, that made the plan choose them.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ConsentPurpose
from app.models.measurement import Measurement
from app.models.player import Player
from app.services import cohort, forecast  # noqa: F401  (forecast puts ml/ on the path)
from app.services.access import Caller, consent_subquery, visible_players
from app.services.views import LATE_BLOOMER, measurement_series

from ml.decisions import measurement as planner  # noqa: E402

SUGGESTED_EVERY_DAYS = 91
MAX_CAPACITY = 200
SMALL_Z = -0.5


def suggested_capacity(squad: int) -> int:
    """Enough places for everyone to be measured about every SUGGESTED_EVERY_DAYS days."""
    return max(1, math.ceil(squad * planner.SESSION_DAYS / SUGGESTED_EVERY_DAYS)) if squad else 0


def _months(days: int) -> str:
    months = round(days / 30.44)
    return "a month" if months <= 1 else f"{months} months"


def reasons(p: planner.Player, today: date, z: float | None) -> list[str]:
    """Why the plan chose this player, in the terms of its value (ml/decisions/measurement.py)."""
    out = []
    age = p.age(today)
    last = p.last_reading()
    recent = sum(1 for d, _ in p.readings if (today - d).days <= 365)
    in_check = age is not None and LATE_BLOOMER.min_age <= age <= LATE_BLOOMER.max_age
    if in_check and recent < LATE_BLOOMER.min_measurements:
        more = LATE_BLOOMER.min_measurements - recent
        out.append(f"{more} more {'reading' if more == 1 else 'readings'} this year before the late-bloomer "
                   "check can see a growth rate")
    if z is not None and z <= SMALL_Z and age is not None and planner.AGE_WINDOW[0] <= age <= planner.AGE_WINDOW[1]:
        out.append("shorter than most of their age group, at the age academies make cuts")
    if last is None:
        out.append("never measured")
    elif (today - last).days > planner.MAX_GAP_DAYS:
        out.append(f"over six months since the last reading ({_months((today - last).days)})")
    elif (today - last).days + planner.SESSION_DAYS > planner.MAX_GAP_DAYS:
        out.append(f"would pass six months without a reading before the next session "
                   f"(last measured {_months((today - last).days)} ago)")
    elif (today - last).days >= 120:
        out.append(f"last measured {_months((today - last).days)} ago")
    return out or ["keeps their readings regular"]


def plan(db: Session, caller: Caller, capacity: int | None, today: date | None = None) -> dict:
    today = today or date.today()
    squad = list(db.execute(visible_players(caller).order_by(Player.full_name)).scalars().unique())
    consented = set(db.execute(consent_subquery(ConsentPurpose.ANALYTICS.value)).scalars())
    eligible = [p for p in squad if p.id in consented]
    heights = measurement_series(db, [p.id for p in eligible], "height_cm")

    # The size-for-age reference: every consented player measured in the last six months.
    since = today - timedelta(days=planner.MAX_GAP_DAYS)
    recent_ids = list(db.execute(select(Measurement.player_id).where(
        Measurement.metric == "height_cm", Measurement.measured_at >= since).distinct()).scalars())
    recent_ids = [pid for pid in recent_ids if pid in consented]
    others = {p.id: p for p in db.execute(select(Player).where(Player.id.in_(recent_ids))).scalars()} if recent_ids else {}
    reference_heights = measurement_series(db, list(others), "height_cm")

    def as_planner(p: Player, series) -> planner.Player:
        return planner.Player(str(p.id), p.sex or "", p.date_of_birth, today - timedelta(days=3650),
                              today + timedelta(days=3650), [(d, h) for d, h in series if d <= today])

    reference = [as_planner(p, reference_heights.get(pid, [])) for pid, p in others.items()]
    zs = planner.height_z(reference, today)
    players = [as_planner(p, heights.get(p.id, [])) for p in eligible]

    suggested = suggested_capacity(len(players))
    capacity = suggested if capacity is None else max(0, min(capacity, MAX_CAPACITY))
    chosen = planner.choose_optimised(players, today, capacity, {}, zs=zs) if players and capacity else []
    by_id = {str(p.id): p for p in eligible}
    pl = {p.id: p for p in players}
    ordered = sorted(chosen, key=lambda pid: -planner.value(pl[pid], today, zs.get(pid)))
    return {
        "capacity": capacity,
        "suggested": suggested,
        "squad": len(squad),
        "planned_from": len(players),
        "without_consent": len(squad) - len(players),
        "players": [{
            "player": by_id[pid],
            "age_label": cohort.age_label(by_id[pid].date_of_birth, today),
            "readings_last_year": sum(1 for d, _ in pl[pid].readings if (today - d).days <= 365),
            "days_since_last": (today - pl[pid].last_reading()).days if pl[pid].last_reading() else None,
            "reasons": reasons(pl[pid], today, zs.get(pid)),
        } for pid in ordered],
    }
