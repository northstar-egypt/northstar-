"""Side-by-side comparison of two to four players."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models.player import Player
from app.schemas.views import ComparisonOut
from app.services import views
from app.services.access import Caller, may_view, visible_players

router = APIRouter(tags=["comparison"])

MAX_PLAYERS = 4


@router.get("/compare", response_model=ComparisonOut)
def compare(
    players: str = Query(description="Comma-separated player ids, two to four."),
    basis: str = Query(default="age", pattern="^(age|maturity)$"),
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> ComparisonOut:
    """Compare players on raw metrics, with a caveat when the comparison is unfair.

    `basis=maturity` is accepted but not honoured: the maturity-offset method is an open ML
    board item. The response says so in `caveat` rather than quietly returning age-based
    numbers under a maturity heading.
    """
    try:
        requested = [uuid.UUID(part.strip()) for part in players.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed player id."
        ) from None

    if not 2 <= len(requested) <= MAX_PLAYERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Compare between 2 and {MAX_PLAYERS} players, got {len(requested)}.",
        )

    found = list(
        db.execute(visible_players(caller).where(Player.id.in_(requested))).scalars().unique()
    )
    # Drop anything the caller may not see rather than reporting which one it was.
    allowed = [player for player in found if may_view(db, caller, player)[0]]

    if len(allowed) < 2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fewer than two of those players are available to you.",
        )

    # Preserve the caller's ordering so the columns match what they asked for.
    order = {player_id: index for index, player_id in enumerate(requested)}
    allowed.sort(key=lambda player: order.get(player.id, 0))

    return ComparisonOut.model_validate(views.build_comparison(db, caller, allowed, basis))
