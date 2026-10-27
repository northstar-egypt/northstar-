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


class EventOutcomeOut(CamelModel):
    key: str
    label: str


class DetailValueOut(CamelModel):
    key: str
    label: str


class EventDetailOut(CamelModel):
    key: str
    label: str
    values: list[DetailValueOut]
    # The outcomes it applies to; empty means all.
    outcomes: list[str] = []
    # [rows, cols] when its values are drawn as a grid (a goal mouth), row by row.
    grid: list[int] | None = None


class EventTypeOut(CamelModel):
    key: str
    label: str
    # The keyboard key the tagging screen binds to it.
    shortcut: str
    outcomes: list[EventOutcomeOut]
    # What a coach can add after the outcome (decision 0007).
    details: list[EventDetailOut] = []


class AnalysisOut(CamelModel):
    key: str
    label: str
    rate_label: str
    min_attempts: int


class SportOut(CamelModel):
    sport: str
    label: str
    role_label: str
    roles: list[str]
    uses_tier: bool
    genders: list[str]
    # What a coach can tag from match video. Empty for a sport with none yet.
    events: list[EventTypeOut] = []
    # Rates read from the tags (GET /analysis/{sport}/{key}).
    analyses: list[AnalysisOut] = []


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
            events=[
                EventTypeOut(
                    key=kind.key,
                    label=kind.label,
                    shortcut=kind.shortcut,
                    outcomes=[EventOutcomeOut(key=o.key, label=o.label) for o in kind.outcomes.values()],
                    details=[
                        EventDetailOut(
                            key=d.key,
                            label=d.label,
                            values=[DetailValueOut(key=k, label=v) for k, v in d.values.items()],
                            outcomes=d.outcomes,
                            grid=list(d.grid) if d.grid else None,
                        )
                        for d in kind.details.values()
                    ],
                )
                for kind in module.events.values()
            ],
            analyses=[
                AnalysisOut(key=a.key, label=a.label, rate_label=a.rate_label, min_attempts=a.min_attempts)
                for a in module.analyses.values()
            ],
        )
        for module in sports.registry().values()
    ]
