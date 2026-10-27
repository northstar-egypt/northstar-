"""Rates read from tagged match events (app/services/event_analysis.py, decision 0007)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.schemas.core import CamelModel
from app.services import event_analysis
from app.services.access import Caller

router = APIRouter(tags=["analysis"])


class ValueOut(CamelModel):
    key: str
    label: str
    attempts: int
    successes: int
    # Null below event_analysis.MIN_FOR_A_RATE attempts: the counts are shown, not a rate.
    rate: float | None = None


class BreakdownOut(CamelModel):
    key: str
    label: str
    # [rows, cols] when the values are a grid (a goal mouth), row by row.
    grid: list[int] | None = None
    # Attempts with this detail recorded.
    recorded: int
    # The outcomes it is recorded for, in words, when not all of them.
    among: str | None = None
    values: list[ValueOut]


class LeaderOut(CamelModel):
    player_id: uuid.UUID
    full_name: str
    position: str | None = None
    age_label: str
    attempts: int
    successes: int
    rate: float


class FocusOut(CamelModel):
    player_id: uuid.UUID
    full_name: str
    attempts: int
    successes: int
    # Null until the player has the analysis's minimum attempts.
    rate: float | None = None
    # Among the players with the minimum, when there are enough of them.
    percentile: int | None = None


class AnalysisOut(CamelModel):
    sport: str
    key: str
    label: str
    rate_label: str
    min_attempts: int
    min_for_a_rate: int
    gender: str
    group: str | None = None
    age_from: int | None = None
    age_to: int | None = None
    genders: list[str]
    groups: list[str]
    population: str
    attempts: int
    successes: int
    rate: float | None = None
    breakdown: list[BreakdownOut]
    leaders: list[LeaderOut]
    # Players with the minimum attempts, named to this caller or not.
    qualifying: int
    player: FocusOut | None = None
    # Tags made by the synthetic data generator rather than a coach.
    generated: int
    note: str


@router.get("/analysis/{sport}/{key}", response_model=AnalysisOut)
def analysis(
    sport: str,
    key: str,
    gender: str | None = None,
    group: str | None = None,
    age_from: int | None = Query(default=None, alias="ageFrom", ge=0, le=60),
    age_to: int | None = Query(default=None, alias="ageTo", ge=0, le=60),
    player: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> AnalysisOut:
    """A success rate from tagged events (finishing, points by stroke), broken down by the
    details coaches add, with the best players the caller may open."""
    try:
        result = event_analysis.analyse(
            db, caller, sport=sport, key=key, gender=gender, group=group,
            age_from=age_from, age_to=age_to, player_id=player,
        )
    except event_analysis.AnalysisError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from None
    return AnalysisOut.model_validate(result)
