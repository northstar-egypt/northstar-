"""The scatter explorer: comparable players on two statistics (app/services/explore.py)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models.player import Player
from app.schemas.views import ScatterOut
from app.services import explore
from app.services.access import Caller, may_view, visible_players

router = APIRouter(tags=["explore"])


@router.get("/explore/scatter", response_model=ScatterOut)
def scatter(
    sport: str | None = None,
    gender: str | None = None,
    group: str | None = None,
    age_from: int | None = Query(default=None, alias="ageFrom", ge=0, le=60),
    age_to: int | None = Query(default=None, alias="ageTo", ge=0, le=60),
    x: str | None = None,
    y: str | None = None,
    focus: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> ScatterOut:
    """Every comparable player on two statistics, with the group's medians.

    `focus` is a player to mark, and to take the sport, gender and position group from when
    those are not given. A focus the caller may not open is ignored exactly as an unknown id
    is, so the response does not say whether that player exists.
    """
    focus_player = None
    if focus is not None:
        found = db.execute(
            visible_players(caller).where(Player.id == focus).limit(1)
        ).scalar_one_or_none()
        if found is not None and may_view(db, caller, found)[0]:
            focus_player = found
    try:
        body = explore.scatter(
            db, caller, sport=sport, gender=gender, group=group, age_from=age_from,
            age_to=age_to, x=x, y=y, focus=focus_player,
        )
    except explore.ExploreError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None
    return ScatterOut.model_validate(body)
