"""Federation oversight: aggregates over the whole population.

Restricted to federation staff and admins. Everything this returns is a count, a median or a
percentage; no player rows leave here, which is what makes a broad-read endpoint acceptable
for a dataset that is mostly about children.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models.enums import Sport
from app.schemas.views import OversightSummaryOut
from app.services import views
from app.services.access import Caller

router = APIRouter(tags=["oversight"])


@router.get("/oversight", response_model=OversightSummaryOut)
def oversight(
    sport: str = Query(default=Sport.FOOTBALL.value),
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> OversightSummaryOut:
    """Coverage and integrity aggregates for one sport.

    `byRegion` is always empty. Coverage by governorate needs a region field on
    Organization, which the schema does not have. Raised in `docs/wireframes/README.md`.
    """
    if not (caller.is_federation or caller.is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Oversight is limited to federation staff.",
        )

    if sport not in {item.value for item in Sport}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown sport {sport!r}."
        )

    return OversightSummaryOut.model_validate(views.build_oversight(db, caller, sport))
