"""Player endpoints: the squad list, the full profile, adding a player, logging a visit.

Reads are scoped by `app.services.access`. A player outside the caller's scope returns 404
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
from app.models.enums import ConsentPurpose
from app.models.player import Player
from app.schemas.core import MeasurementOut, PlayerOut
from app.schemas.views import PlayerProfileOut, ProfileSummaryOut, SquadRowOut
from app.schemas.writes import (
    ConsentWithdrawalIn,
    ConsentWithdrawnOut,
    MeasurementBatchIn,
    MeasurementsSavedOut,
    PlayerCreatedOut,
    PlayerCreateIn,
)
from app.services import summary, views, writes
from app.services.access import (
    Caller,
    consent_state,
    has_consent,
    may_create_player,
    may_view,
    permissions,
    visible_players,
)

router = APIRouter(tags=["players"])


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


def _viewable_player(db: Session, caller: Caller, player_id: uuid.UUID) -> Player:
    """The player, or 404 if they do not exist or the caller may not see them."""
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
    return player


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
    player = _viewable_player(db, caller, player_id)
    return PlayerProfileOut.model_validate(views.build_profile(db, caller, player))


@router.get("/players/{player_id}/summary", response_model=ProfileSummaryOut)
def player_summary(
    player_id: uuid.UUID,
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> ProfileSummaryOut:
    """A few sentences about the profile, written by the local model and checked.

    Separate from the profile because writing it takes seconds on a laptop, and the profile
    should not wait for it. Built from the same filtered profile the caller sees, so it can
    only repeat what the page already shows. See app/services/summary.py.
    """
    player = _viewable_player(db, caller, player_id)
    if not has_consent(db, player.id, ConsentPurpose.ANALYTICS.value):
        # A model writing about the player is analytics on their data, however carefully its
        # sentences are checked. The model is not asked at all.
        return ProfileSummaryOut(
            summary=None,
            note="Analytics consent is not in effect for this player, so no summary is "
            "written about them.",
        )
    result = summary.summarise(views.build_profile(db, caller, player))
    return ProfileSummaryOut(summary=result.text, note=result.note, model=result.model)


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def _refusal(exc: writes.WriteRejected | writes.NeedsConfirmation) -> HTTPException:
    """The two ways a write does not happen, as responses a screen can act on.

    422 means fix it. 409 means confirm it: the body lists each reading that looked wrong,
    and resending with `acknowledgeWarnings: true` saves it. Both carry a list rather than one
    message, so a coach sees every problem at once instead of one per attempt.
    """
    if isinstance(exc, writes.NeedsConfirmation):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "Some readings look unusual. Nothing was saved. Check them, then resend "
                    "with acknowledgeWarnings set to confirm they are right."
                ),
                "warnings": exc.warnings,
            },
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"message": "Nothing was saved.", "problems": exc.problems},
    )


@router.post(
    "/players", response_model=PlayerCreatedOut, status_code=status.HTTP_201_CREATED
)
def create_player(
    payload: PlayerCreateIn,
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> PlayerCreatedOut:
    """Add a player to the caller's organization, optionally with their first measurements.

    One transaction: the player, their affiliation, the first visit and the audit rows are
    all saved or none are. The affiliation is not optional, because a player with no current
    organization is invisible to every coach and would be saved only to be lost.

    Minor status is computed here from the date of birth, never taken from the client. The
    sign-up consent form is required and saved in the same transaction: a guardian's
    signature for a minor, the player's own for an adult. So a new player is visible to
    scouts from the start, and a later withdrawal is what would hide a minor again.
    """
    organization_id, reason = may_create_player(caller, payload.organization_id)
    if organization_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)

    try:
        player, measurements, warnings = writes.create_player(
            db,
            payload=payload,
            organization_id=organization_id,
            actor_user_id=caller.user_id,
        )
    except (writes.WriteRejected, writes.NeedsConfirmation) as exc:
        # Every check runs before the first insert, so there is nothing to roll back.
        raise _refusal(exc) from exc
    db.commit()

    return PlayerCreatedOut(
        player=PlayerOut.model_validate(player),
        organization_id=organization_id,
        measurements=[MeasurementOut.model_validate(row) for row in measurements],
        acknowledged_warnings=warnings,
        consent_granted_by=(
            f"guardian:{payload.consent.guardian_name}" if player.is_minor else "player"
        ),
    )


@router.post(
    "/players/{player_id}/measurements",
    response_model=MeasurementsSavedOut,
    status_code=status.HTTP_201_CREATED,
)
def log_measurements(
    player_id: uuid.UUID,
    batch: MeasurementBatchIn,
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> MeasurementsSavedOut:
    """Log one visit's measurements for a player the caller may log for.

    A player the caller cannot see is 404, for the same reason as the profile. A player they
    can see but not log for (a scout, federation staff) is 403: they already know the player
    exists, so there is nothing left to hide, and 403 tells them the true reason.
    """
    player = db.execute(
        visible_players(caller).where(Player.id == player_id).limit(1)
    ).scalar_one_or_none()
    if player is None or not may_view(db, caller, player)[0]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such player.")

    if not permissions(db, caller, player)["can_log"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role does not permit logging measurements.",
        )

    try:
        rows, warnings = writes.log_measurements(
            db, player=player, batch=batch, actor_user_id=caller.user_id
        )
    except (writes.WriteRejected, writes.NeedsConfirmation) as exc:
        # Every check runs before the first insert, so there is nothing to roll back.
        raise _refusal(exc) from exc
    db.commit()

    return MeasurementsSavedOut(
        measurements=[MeasurementOut.model_validate(row) for row in rows],
        acknowledged_warnings=warnings,
    )


@router.post("/players/{player_id}/consent/withdraw", response_model=ConsentWithdrawnOut)
def withdraw_consent(
    player_id: uuid.UUID,
    payload: ConsentWithdrawalIn,
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> ConsentWithdrawnOut:
    """Record a guardian's (or an adult player's) withdrawal of part of the sign-up consent.

    Anyone who may edit the record may record it: an admin, the player's coach, or the
    player. Withdrawing only ever takes access away, so there is nothing to protect by making
    it harder. Scouts and federation staff may not, since they do not hold the form. It takes
    effect at once everywhere consent is checked: a withdrawn scouting consent hides a minor
    from scouts, and a withdrawn analytics consent ends their rating, forecast, percentiles,
    talent flags and search matches.

    Same 404/403 split as logging measurements. Repeating a withdrawal is harmless: purposes
    already not in effect come back under `alreadyWithdrawn`.
    """
    player = db.execute(
        visible_players(caller).where(Player.id == player_id).limit(1)
    ).scalar_one_or_none()
    if player is None or not may_view(db, caller, player)[0]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such player.")

    if not permissions(db, caller, player)["can_edit"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role does not permit recording a consent withdrawal.",
        )

    try:
        withdrawn, already, withdrawn_by = writes.withdraw_consent(
            db,
            player=player,
            purposes=payload.purposes,
            guardian_name=payload.guardian_name,
            actor_user_id=caller.user_id,
        )
    except writes.WriteRejected as exc:
        raise _refusal(exc) from exc
    db.commit()

    return ConsentWithdrawnOut(
        withdrawn=withdrawn,
        already_withdrawn=already,
        withdrawn_by=withdrawn_by,
        consents=consent_state(db, player.id),
    )
