"""Federation oversight: aggregates over the whole population.

Restricted to federation staff and admins. `/oversight` returns counts, medians and percentages;
no player rows leave it, which is what makes a broad-read endpoint acceptable for a dataset that
is mostly about children. `/oversight/strongest` names players, and only to those same staff, who
may open any record: only players whose rating the profile would show, with analytics consent.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models.enums import Sport
from app.models.player import Player
from app.schemas.core import CamelModel
from app.schemas.views import OversightSummaryOut
from app.services import rating, views
from app.services.access import Caller

router = APIRouter(tags=["oversight"])


@router.get("/oversight", response_model=OversightSummaryOut)
def oversight(
    sport: str = Query(default=Sport.FOOTBALL.value),
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> OversightSummaryOut:
    """Coverage and integrity aggregates for one sport.

    `byRegion` lists all 27 governorates, with the players of this sport at a club in each
    and the population, so a governorate the platform has not reached shows as a gap.
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


class StrongestPlayerOut(CamelModel):
    player_id: str
    full_name: str
    organization: str | None = None
    # Share of points against an average registered opponent, with its range (0 to 1).
    point_share: float
    low: float
    high: float
    rated_matches: int


class StrongestGroupOut(CamelModel):
    gender: str
    # Who the rating is among, in words.
    population: str
    players: list[StrongestPlayerOut]


@router.get("/oversight/strongest", response_model=list[StrongestGroupOut])
def strongest_rated(
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> list[StrongestGroupOut]:
    """The strongest rated table tennis players, per gender: the federation home's own view of a
    sport with no clubs on record to report coverage for."""
    if not (caller.is_federation or caller.is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Oversight is limited to federation staff.",
        )
    groups = rating.strongest(db)
    ids = [uuid.UUID(p["player_id"]) for rows in groups.values() for p in rows]
    names = dict(db.execute(select(Player.id, Player.full_name).where(Player.id.in_(ids))).all()) if ids else {}
    clubs = views.organization_names(db, ids)
    return [
        StrongestGroupOut(
            gender=gender,
            population=f"registered {rating.GENDER_WORDS.get(gender, 'players')} in table tennis",
            players=[
                StrongestPlayerOut(
                    full_name=names[uuid.UUID(p["player_id"])], organization=clubs.get(uuid.UUID(p["player_id"])), **p
                )
                for p in rows
            ],
        )
        for gender, rows in sorted(groups.items())
    ]
