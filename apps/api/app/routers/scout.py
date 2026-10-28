"""The scout's home and shortlist. See app/services/scout_home.py."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi import status as http_status
from pydantic import Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.schemas.core import CamelModel
from app.services import scout_home
from app.services.access import Caller

router = APIRouter(tags=["scout"])


def require_scouting(caller: Caller = Depends(current_user)) -> Caller:
    """Scouts and federation staff: the roles that look for players across clubs."""
    if not (caller.is_scout or caller.is_federation):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Shortlists are for scouts and federation staff.",
        )
    return caller


class PlayerCardOut(CamelModel):
    player_id: str
    full_name: str
    position: str | None = None
    tier: str | None = None
    age_label: str
    club: str | None = None
    is_minor: bool


class ShortlistItemOut(PlayerCardOut):
    note: str
    saved_at: str


class BreakoutItemOut(PlayerCardOut):
    season: str
    reason: str
    minutes_before: int
    minutes_after: int


class LateBloomerItemOut(PlayerCardOut):
    reason: str
    status: str


class ScoutHomeOut(CamelModel):
    first_name: str | None = None
    shortlist: list[ShortlistItemOut]
    # Saved players the caller can no longer see (consent withdrawn, record merged away).
    withheld: int
    breakouts: list[BreakoutItemOut]
    # The league season the breakouts are from; null when there are no league seasons.
    breakout_season: str | None = None
    late_bloomers: list[LateBloomerItemOut]


class ShortlistNoteIn(CamelModel):
    note: str = Field(default="", max_length=scout_home.NOTE_MAX)


class ShortlistIdsOut(CamelModel):
    player_ids: list[str]


@router.get("/home/scout", response_model=ScoutHomeOut)
def scout_home_page(db: Session = Depends(get_db), caller: Caller = Depends(require_scouting)) -> ScoutHomeOut:
    """What is new for this scout: their shortlist, this season's breakouts, late bloomers."""
    return ScoutHomeOut.model_validate(scout_home.home(db, caller))


@router.get("/shortlist", response_model=ShortlistIdsOut)
def shortlist(db: Session = Depends(get_db), caller: Caller = Depends(require_scouting)) -> ShortlistIdsOut:
    """The ids on the caller's shortlist, for the profile's save button."""
    return ShortlistIdsOut(player_ids=scout_home.shortlist_ids(db, caller))


@router.put("/shortlist/{player_id}", status_code=http_status.HTTP_204_NO_CONTENT)
def save_to_shortlist(
    player_id: uuid.UUID,
    body: ShortlistNoteIn,
    db: Session = Depends(get_db),
    caller: Caller = Depends(require_scouting),
) -> Response:
    """Save a player, or change the note on a saved one. 404 if the caller may not see them."""
    try:
        scout_home.save(db, caller, player_id, body.note)
    except scout_home.NotVisible:
        raise HTTPException(status_code=404, detail="No such player.") from None
    db.commit()
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)


@router.delete("/shortlist/{player_id}", status_code=http_status.HTTP_204_NO_CONTENT)
def remove_from_shortlist(
    player_id: uuid.UUID,
    db: Session = Depends(get_db),
    caller: Caller = Depends(require_scouting),
) -> Response:
    if not scout_home.remove(db, caller, player_id):
        raise HTTPException(status_code=404, detail="That player is not on your shortlist.")
    db.commit()
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)
