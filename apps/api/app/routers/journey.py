"""Parts 6 to 9 of "find the next <pro>": weekly report, game journey, drills done, academy
leaderboard and scout alerts. See app/services/journey.py."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models.enums import FootballTier
from app.routers.players import _viewable_player
from app.schemas.core import CamelModel
from app.services import journey
from app.services.access import Caller, permissions

router = APIRouter(tags=["journey"])


class LevelOut(CamelModel):
    name: str
    next_name: str | None = None
    next_at: int | None = None


class BadgeOut(CamelModel):
    key: str
    label: str
    earned: bool


class IdolOut(CamelModel):
    pro_id: uuid.UUID
    name: str
    position: str | None = None
    percent: int
    # The match to the same pro from older matches only; None when it cannot be computed.
    before: int | None = None
    weeks: int


class JourneyOut(CamelModel):
    xp: int | None = None
    level: LevelOut | None = None
    minutes: int = 0
    drills: int = 0
    badges: list[BadgeOut] = []
    idol: IdolOut | None = None
    note: str


class WeekOut(CamelModel):
    from_: str = Field(alias="from")
    to: str
    matches: int
    minutes: int
    drills: int
    xp: int


class ChangeOut(CamelModel):
    key: str
    label: str
    before: float
    now: float
    unit: str


class WeeklyReportOut(CamelModel):
    week: WeekOut | None = None
    improved: list[ChangeOut] = []
    dropped: list[ChangeOut] = []
    goal: str | None = None
    note: str


class DrillIn(CamelModel):
    statistic: str = Field(min_length=1, max_length=40)
    drill: str = Field(min_length=1, max_length=120)


class DrillLoggedOut(CamelModel):
    id: uuid.UUID
    done_on: str


class LeaderRowOut(CamelModel):
    player_id: uuid.UUID
    full_name: str
    position: str | None = None
    age_label: str
    xp: int
    minutes: int
    drills: int


class LeaderboardOut(CamelModel):
    items: list[LeaderRowOut] = []
    note: str


class WatchOut(CamelModel):
    player_id: uuid.UUID
    pro_id: uuid.UUID
    percent: int | None = None


class AlertOut(CamelModel):
    player_id: uuid.UUID
    full_name: str
    pro_id: uuid.UUID
    pro_name: str
    before: int | None = None
    now: int | None = None
    alert: bool


class AlertsOut(CamelModel):
    items: list[AlertOut] = []
    note: str


def _youth(db: Session, caller: Caller, player_id: uuid.UUID):
    player = _viewable_player(db, caller, player_id)
    if player.tier != FootballTier.YOUTH.value or player.primary_sport != "football":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Only academy footballers have this.")
    return player


@router.get("/players/{player_id}/journey", response_model=JourneyOut)
def player_journey(player_id: uuid.UUID, db: Session = Depends(get_db),
                   caller: Caller = Depends(current_user)) -> JourneyOut:
    """XP, level, badges and idol for an academy player (part 7)."""
    return JourneyOut.model_validate(journey.journey(db, caller, _youth(db, caller, player_id)))


@router.get("/players/{player_id}/weekly-report", response_model=WeeklyReportOut)
def player_weekly_report(player_id: uuid.UUID, db: Session = Depends(get_db),
                         caller: Caller = Depends(current_user)) -> WeeklyReportOut:
    """This week, what went up or down, and a next goal (part 6)."""
    return WeeklyReportOut.model_validate(journey.weekly_report(db, _youth(db, caller, player_id)))


@router.post("/players/{player_id}/drills", response_model=DrillLoggedOut, status_code=201)
def log_drill(player_id: uuid.UUID, payload: DrillIn, db: Session = Depends(get_db),
              caller: Caller = Depends(current_user)) -> DrillLoggedOut:
    """Record a drill done today: the player's coach, or the player themselves."""
    player = _youth(db, caller, player_id)
    if not (permissions(db, caller, player)["can_log"] or caller.linked_player_id == player.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only the player's coach or the player can record drills.")
    row = journey.log_drill(db, caller, player, payload.statistic, payload.drill)
    db.commit()
    return DrillLoggedOut(id=row.id, done_on=row.done_on.isoformat())


@router.get("/leaderboard", response_model=LeaderboardOut)
def academy_leaderboard(db: Session = Depends(get_db), caller: Caller = Depends(current_user)) -> LeaderboardOut:
    """This week's top XP earners among the academy players the caller may see (part 8)."""
    return LeaderboardOut.model_validate(journey.leaderboard(db, caller))


def _scouting(caller: Caller = Depends(current_user)) -> Caller:
    if not (caller.is_scout or caller.is_federation):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Watching players is for scouts and federation staff.")
    return caller


@router.put("/players/{player_id}/watch/{pro_id}", response_model=WatchOut)
def watch(player_id: uuid.UUID, pro_id: uuid.UUID, db: Session = Depends(get_db),
          caller: Caller = Depends(_scouting)) -> WatchOut:
    """Follow an academy player against a professional (part 9)."""
    player = _youth(db, caller, player_id)
    pro = _viewable_player(db, caller, pro_id)
    out = journey.watch(db, caller, player, pro)
    db.commit()
    return WatchOut.model_validate(out)


@router.delete("/players/{player_id}/watch/{pro_id}", status_code=204)
def unwatch(player_id: uuid.UUID, pro_id: uuid.UUID, db: Session = Depends(get_db),
            caller: Caller = Depends(_scouting)) -> Response:
    journey.unwatch(db, caller, player_id, pro_id)
    db.commit()
    return Response(status_code=204)


@router.get("/alerts", response_model=AlertsOut)
def alerts(db: Session = Depends(get_db), caller: Caller = Depends(_scouting)) -> AlertsOut:
    """The players this user follows, with alerts where the match has jumped."""
    return AlertsOut.model_validate(journey.alerts(db, caller))


@router.post("/alerts/seen", response_model=AlertsOut)
def alerts_seen(db: Session = Depends(get_db), caller: Caller = Depends(_scouting)) -> AlertsOut:
    """Mark every alert as seen: the current match becomes the new starting point."""
    out = journey.alerts(db, caller, mark_seen=True)
    db.commit()
    return AlertsOut.model_validate(out)
