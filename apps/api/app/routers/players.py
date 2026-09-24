"""Player endpoints: the squad list and the full profile.

Both are scoped by `app.services.access`. A player outside the caller's scope returns 404
rather than 403, because "403 on a player you may not see" tells an unauthorised caller that
the player exists, which is the leak the threat model's first entry is about.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models.player import Player
from app.schemas.core import SessionUserOut
from app.schemas.views import PlayerProfileOut, SquadRowOut
from app.services import views
from app.services.access import Caller, may_view, visible_players

router = APIRouter(tags=["players"])


@router.get("/me", response_model=SessionUserOut)
def me(caller: Caller = Depends(current_user)) -> SessionUserOut:
    """Who the API believes is calling.

    Until the security track's auth decision lands this reflects the development identity
    header, not a session. See `app.deps`.
    """
    return SessionUserOut(
        id=caller.user_id,
        full_name=caller.full_name,
        email=caller.email,
        role=caller.role,
        organization_id=caller.organization_id,
        organization_name=caller.organization_name,
        linked_player_id=caller.linked_player_id,
    )


@router.get("/players", response_model=list[SquadRowOut])
def list_players(
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
    organization_id: uuid.UUID | None = Query(
        default=None,
        description=(
            "Restrict to one organization. A coach is restricted to their own regardless."
        ),
    ),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[SquadRowOut]:
    """The squad table.

    Everything the table needs is on the row, including days since the last log and the last
    six height readings for the sparkline, because fetching those per player is what makes
    this screen slow.
    """
    stmt = visible_players(caller).order_by(Player.full_name).limit(limit)

    if organization_id is not None:
        from app.models.player_organization import PlayerOrganization

        stmt = stmt.where(
            Player.id.in_(
                select(PlayerOrganization.player_id)
                .where(PlayerOrganization.organization_id == organization_id)
                .where(PlayerOrganization.end_date.is_(None))
            )
        )

    rows = views.build_squad(db, caller, stmt)
    return [SquadRowOut.model_validate(row) for row in rows]


@router.get("/players/{player_id}/profile", response_model=PlayerProfileOut)
def player_profile(
    player_id: uuid.UUID,
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> PlayerProfileOut:
    """The player profile, already filtered for the caller's role and consent.

    The response carries a `permissions` object so the frontend never has to infer what to
    render from the role. Anything the caller may not see is absent rather than hidden.
    """
    player = db.execute(
        visible_players(caller).where(Player.id == player_id).limit(1)
    ).scalar_one_or_none()

    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such player.")

    allowed, reason = may_view(db, caller, player)
    if not allowed:
        # 404 and not 403. A scout who may not see a minor should not learn that the minor
        # exists, and a distinguishable status code is exactly how they would.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such player.")

    return PlayerProfileOut.model_validate(views.build_profile(db, caller, player))
