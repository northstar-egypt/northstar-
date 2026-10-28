"""Team gap analysis (decision 0003): where a club is weak and which players are strong there,
and national team mode, where the federation names the needs. See app/services/gaps.py."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.schemas.core import CamelModel
from app.services import gaps
from app.services.access import Caller

router = APIRouter(tags=["gaps"], prefix="/gaps")


def require_scouting(caller: Caller = Depends(current_user)) -> Caller:
    """Scouts and federation staff only, as decision 0003 proposes."""
    if not (caller.is_scout or caller.is_federation):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Team gap analysis is limited to scouts and federation staff.",
        )
    return caller


class GapClubOut(CamelModel):
    id: str
    name: str
    competition: str
    seasons: list[str]


class GapGroupOut(CamelModel):
    key: str
    label: str
    attributes: list[str]


class GapAttributeOut(CamelModel):
    key: str
    label: str
    # Its season figure repeats poorly between half seasons (ml/README.md).
    low_reliability: bool
    percent: bool


class GapOptionsOut(CamelModel):
    clubs: list[GapClubOut]
    groups: list[GapGroupOut]
    attributes: list[GapAttributeOut]
    min_minutes: int
    min_cohort: int


class CandidateOut(CamelModel):
    player_id: str
    full_name: str
    position: str | None = None
    club: str | None = None
    competition: str
    season: str
    minutes: int
    # Each statistic's value: a rate per 90, or a share from 0 to 1.
    values: dict[str, float | None]
    # Null for an attribute with too few players to compare with.
    percentiles: dict[str, int | None]
    # The mean of the percentiles: the ranking rule. Null when unranked.
    mean: float | None = None
    # Ranked players of the group in the candidate's league and season.
    population: int
    abroad: bool


class NeedOut(CamelModel):
    group: str
    label: str
    attributes: list[str]
    candidates: list[CandidateOut]
    # Players whose league has too few ranked players of the group to place them.
    unranked: list[CandidateOut] = []


class ProfileMetricOut(CamelModel):
    key: str
    label: str
    value: float | None = None
    # 1 is the best in the league; null when it cannot be ranked.
    rank: int | None = None
    of: int
    better: str
    weak: bool
    bottom_unstable: bool
    percent: bool
    no_player_link: str | None = None
    needs: list[NeedOut] = []


class SquadPlayerOut(CamelModel):
    player_id: str
    full_name: str
    position: str | None = None
    minutes: int
    share: float
    percentiles: dict[str, int | None]
    ranked: bool


class CoverageOut(CamelModel):
    group: str
    label: str
    attributes: list[str]
    population: int
    players: list[SquadPlayerOut]


class GapClubRefOut(CamelModel):
    id: str
    name: str | None = None
    competition: str
    season: str


class ClubGapsOut(CamelModel):
    club: GapClubRefOut
    profile: list[ProfileMetricOut]
    coverage: list[CoverageOut]
    min_minutes: int


class NationalGapsOut(CamelModel):
    needs: list[NeedOut]
    min_minutes: int


@router.get("", response_model=GapOptionsOut)
def gap_options(db: Session = Depends(get_db), caller: Caller = Depends(require_scouting)) -> GapOptionsOut:
    """The clubs with team seasons, and the groups and statistics national team mode can ask for."""
    return GapOptionsOut.model_validate(gaps.options(db))


@router.get("/club/{club_id}", response_model=ClubGapsOut)
def club_gaps(
    club_id: uuid.UUID,
    season: str | None = Query(default=None, description="e.g. 2025/26; the latest by default"),
    db: Session = Depends(get_db),
    caller: Caller = Depends(require_scouting),
) -> ClubGapsOut:
    """A club's team profile against its league, its squad by position group, and candidates
    for each weakness stable enough to act on."""
    try:
        return ClubGapsOut.model_validate(gaps.club(db, caller, club_id, season))
    except gaps.NotFound:
        raise HTTPException(status_code=404, detail="No team season for that club and season.") from None


@router.get("/national", response_model=NationalGapsOut)
def national_gaps(
    need: list[str] = Query(description="group:attribute,attribute, e.g. full_backs:crosses_per_90,tackles_per_90"),
    db: Session = Depends(get_db),
    caller: Caller = Depends(require_scouting),
) -> NationalGapsOut:
    """Egypt-eligible players, at home and abroad, for needs the federation names."""
    asks = []
    for item in need[:6]:
        group, _, attributes = item.partition(":")
        asks.append((group, [a for a in attributes.split(",") if a]))
    try:
        return NationalGapsOut.model_validate(gaps.national(db, caller, asks))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
