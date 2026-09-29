"""The sport modules, as the screens need them.

Public within the API's usual identity rule: any signed-in caller may read which sports exist
and what their roles are called. Nothing here is about a player.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app import sports
from app.deps import current_user
from app.schemas.core import CamelModel
from app.services.access import Caller

router = APIRouter(tags=["sports"])


class SportOut(CamelModel):
    sport: str
    label: str
    role_label: str
    roles: list[str]
    uses_tier: bool
    genders: list[str]


@router.get("/sports", response_model=list[SportOut])
def list_sports(caller: Caller = Depends(current_user)) -> list[SportOut]:
    """Every sport the platform has a module for, from `packages/shared/sports`.

    The add-player screen builds its sport and role pickers from this, so a new module file
    makes a new sport loggable without a frontend change.
    """
    return [
        SportOut(
            sport=module.sport,
            label=module.label,
            role_label=module.role_label,
            roles=module.roles,
            uses_tier=module.uses_tier,
            genders=module.genders,
        )
        for module in sports.registry().values()
    ]
