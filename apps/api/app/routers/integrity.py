"""The integrity board: a work queue for flags raised by the models.

Fraud, duplicate and anomaly in one list. They are different models with different evidence,
but they are the same job for the person reviewing: look, decide, move on. Splitting them into
three screens would triple the navigation and halve the throughput
(`docs/wireframes/08-integrity-board.html`).

Restricted to federation staff and admins. The wireframe raises a conflict-of-interest
question this does not answer, which is whether an academy officer should be able to clear
flags on their own academy's records. Nobody below federation can reach the board at all
today, so the situation cannot arise yet, and the question is recorded in `docs/schema.md`
rather than quietly resolved here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models.enums import FlagStatus
from app.models.flag import Flag
from app.schemas.views import FlagDecisionRequest, IntegrityFlagOut
from app.services import flags as flag_service
from app.services.access import Caller

router = APIRouter(tags=["integrity"], prefix="/integrity")


def require_reviewer(caller: Caller = Depends(current_user)) -> Caller:
    """Federation staff and admins only.

    A dependency rather than a check inside the handler, because FastAPI resolves
    dependencies before it validates the request body. Written the other way round, a scout
    posting a malformed decision got a 422 describing what was wrong with their body, which
    is a small thing to tell someone who is not allowed to post at all. Now they get 403
    whatever they send.
    """
    if not (caller.is_federation or caller.is_admin):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="The integrity board is limited to federation staff.",
        )
    return caller


@router.get("/flags", response_model=list[IntegrityFlagOut])
def list_flags(
    db: Session = Depends(get_db),
    caller: Caller = Depends(require_reviewer),
    status: str | None = Query(
        default=FlagStatus.OPEN.value,
        description="Filter by status. Pass an empty string for every status.",
    ),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[IntegrityFlagOut]:
    """The review queue, newest first.

    Each flag carries the evidence it was raised on and its full history, because a reviewer
    has to be able to disagree with the model rather than rubber-stamp it, and because two
    reviewers should not both work the same case.
    """
    if status and status not in {item.value for item in FlagStatus}:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown status {status!r}.",
        )

    rows = flag_service.list_integrity_flags(db, status=status or None, limit=limit)
    return [IntegrityFlagOut.model_validate(row) for row in rows]


@router.post("/flags/{flag_id}/decision", response_model=IntegrityFlagOut)
def decide_flag(
    flag_id: uuid.UUID,
    request: FlagDecisionRequest,
    db: Session = Depends(get_db),
    caller: Caller = Depends(require_reviewer),
) -> IntegrityFlagOut:
    """Record a decision on a flag, with the reason.

    Writes the new status, an append-only event saying who decided what and why, and an audit
    row. The reason is required: each decision plus its reason is a labelled example, and
    labelled examples are what the detectors' precision and recall are computed from.
    """
    if request.decision not in flag_service.DECISION_ACTIONS:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Decision must be one of "
                f"{sorted(flag_service.DECISION_ACTIONS)}, got {request.decision!r}."
            ),
        )

    if not request.reason.strip():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="A decision needs a reason.",
        )

    flag = db.get(Flag, flag_id)
    if flag is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="No such flag."
        )

    flag_service.decide(
        db,
        flag=flag,
        decision=request.decision,
        reason=request.reason.strip(),
        actor_user_id=caller.user_id,
    )
    db.commit()

    updated = flag_service.list_integrity_flags(db, status=None, limit=500)
    for row in updated:
        if row["id"] == str(flag_id):
            return IntegrityFlagOut.model_validate(row)

    raise HTTPException(
        status_code=http_status.HTTP_404_NOT_FOUND, detail="No such flag."
    )
