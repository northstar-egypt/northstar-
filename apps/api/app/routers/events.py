"""Match events tagged from video (app/services/events.py)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models.match_event import MatchEvent
from app.models.player import Player
from app.schemas.core import CamelModel
from app.services import events
from app.services.access import Caller, may_view, permissions, visible_players

router = APIRouter(tags=["events"])


class EventIn(CamelModel):
    player_id: uuid.UUID
    match_date: date
    match_label: str | None = Field(default=None, max_length=events.MAX_LABEL)
    event_type: str
    outcome: str
    x: float | None = None
    y: float | None = None
    video_seconds: float | None = None


class EventOut(CamelModel):
    id: uuid.UUID
    player_id: uuid.UUID
    # Only on a match's list, where several players' tags are shown together.
    player_name: str | None = None
    match_date: date
    match_label: str | None = None
    event_type: str
    outcome: str
    x: float | None = None
    y: float | None = None
    video_seconds: float | None = None


class MatchPlayerOut(CamelModel):
    player_id: uuid.UUID
    player_name: str
    # Match totals the tags add up to, by the sport module's `counts`.
    tagged: dict[str, int]
    # The same totals as the coach logged them for that date; null when nothing was logged.
    logged: dict[str, float | int | None] | None = None


class MatchTagsOut(CamelModel):
    match_date: date
    match_label: str | None = None
    events: list[EventOut] = []
    players: list[MatchPlayerOut] = []


class PlayerEventsOut(CamelModel):
    events: list[EventOut] = []
    matches: int = 0
    # "<type>.<outcome>" -> how many.
    counts: dict[str, int] = {}
    note: str


def _player_to_tag(db: Session, caller: Caller, player_id: uuid.UUID) -> Player:
    """404 for a player the caller cannot see; 403 for one they see but may not log for."""
    player = db.execute(
        visible_players(caller).where(Player.id == player_id).limit(1)
    ).scalar_one_or_none()
    if player is None or not may_view(db, caller, player)[0]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such player.")
    if not permissions(db, caller, player)["can_log"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role does not permit tagging this player's matches.",
        )
    return player


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def tag_event(
    payload: EventIn,
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> EventOut:
    """Save one event tagged from video."""
    player = _player_to_tag(db, caller, payload.player_id)
    try:
        event = events.tag(db, caller, player, payload.model_dump())
    except events.TagRejected as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error.problems
        ) from None
    db.commit()
    return EventOut.model_validate(events.event_out(event))


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def untag_event(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> Response:
    """Undo a tag. 404 unless the caller may change that player's tags, so a tag's existence is
    not confirmed to anyone else."""
    event = db.get(MatchEvent, event_id)
    if event is None or not events.may_change(db, caller, event):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such event.")
    events.remove(db, caller, event)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/events", response_model=MatchTagsOut)
def match_events(
    match_date: date = Query(alias="matchDate"),
    match_label: str | None = Query(default=None, alias="matchLabel"),
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> MatchTagsOut:
    """One match's tags for the caller's own club, as the tagging screen lists them."""
    if caller.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Matches are listed by club, and your account has none.",
        )
    return MatchTagsOut.model_validate(events.match_tags(db, caller, match_date, match_label))


@router.get("/players/{player_id}/events", response_model=PlayerEventsOut)
def player_events(
    player_id: uuid.UUID,
    event_type: str | None = Query(default=None, alias="type"),
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> PlayerEventsOut:
    """A player's tagged events, for whoever may open the player."""
    player = db.execute(
        visible_players(caller).where(Player.id == player_id).limit(1)
    ).scalar_one_or_none()
    if player is None or not may_view(db, caller, player)[0]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such player.")
    return PlayerEventsOut.model_validate(events.player_events(db, player, event_type))
