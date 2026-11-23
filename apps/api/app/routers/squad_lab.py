"""Squad Lab: try line-ups, see how neighbours fit. See app/services/squad_lab.py.

Who may do what
---------------
- Coaches pick from their own organization and save squads for it.
- Scouts and federation staff pick from everyone they may see and try line-ups, but cannot
  save one or see a club's saved squads.
- Players and admins have no use for it and are refused.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi import status as http_status
from pydantic import Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.schemas.core import CamelModel
from app.services import squad_lab
from app.services.access import Caller

router = APIRouter(prefix="/squad-lab", tags=["squad lab"])


def require_lab(caller: Caller = Depends(current_user)) -> Caller:
    if not (caller.is_coach or caller.is_scout or caller.is_federation):
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN,
                            detail="Squad Lab is for managers, scouts and federation staff.")
    return caller


def require_saving(caller: Caller = Depends(require_lab)) -> Caller:
    if not squad_lab.may_save(caller):
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN,
                            detail="Only a club's managers can save squads. You can still try line-ups.")
    return caller


class LineupIn(CamelModel):
    formation: str = Field(max_length=20)
    slots: dict[str, str | None] = Field(default_factory=dict, max_length=18)


class SquadIn(LineupIn):
    name: str = Field(max_length=squad_lab.NAME_MAX)


def _bad(exc: squad_lab.SquadLabError) -> HTTPException:
    return HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/evaluate")
def evaluate(body: LineupIn, db: Session = Depends(get_db), caller: Caller = Depends(require_lab)) -> dict:
    """Score a line-up: each player in his slot, each link between neighbours, the team."""
    try:
        result = squad_lab.evaluate(db, caller, body.formation, body.slots)
    except squad_lab.SquadLabError as exc:
        raise _bad(exc) from None
    result["maySave"] = squad_lab.may_save(caller)
    return result


@router.get("/candidates")
def candidates(
    role: str = Query(max_length=8),
    q: str = Query(default="", max_length=80),
    exclude: str = Query(default="", max_length=600, description="Comma-separated player ids already placed."),
    db: Session = Depends(get_db),
    caller: Caller = Depends(require_lab),
) -> dict:
    """Players the caller may see for one slot, those who play there and score best first."""
    try:
        return squad_lab.candidates(db, caller, role, q, [p for p in exclude.split(",") if p])
    except squad_lab.SquadLabError as exc:
        raise _bad(exc) from None


@router.get("/squads")
def list_squads(db: Session = Depends(get_db), caller: Caller = Depends(require_lab)) -> dict:
    """The caller's club's saved squads. Empty for scouts and federation staff."""
    return {"maySave": squad_lab.may_save(caller), "squads": squad_lab.list_squads(db, caller)}


@router.get("/squads/{squad_id}")
def get_squad(squad_id: uuid.UUID, db: Session = Depends(get_db), caller: Caller = Depends(require_saving)) -> dict:
    try:
        return squad_lab.get_squad(db, caller, squad_id)
    except squad_lab.NotFound:
        raise HTTPException(status_code=404, detail="No such squad.") from None


@router.post("/squads", status_code=http_status.HTTP_201_CREATED)
def create_squad(body: SquadIn, db: Session = Depends(get_db), caller: Caller = Depends(require_saving)) -> dict:
    try:
        out = squad_lab.save_squad(db, caller, body.name, body.formation, body.slots)
    except squad_lab.SquadLabError as exc:
        raise _bad(exc) from None
    db.commit()
    return out


@router.put("/squads/{squad_id}")
def update_squad(squad_id: uuid.UUID, body: SquadIn, db: Session = Depends(get_db),
                 caller: Caller = Depends(require_saving)) -> dict:
    try:
        out = squad_lab.save_squad(db, caller, body.name, body.formation, body.slots, squad_id)
    except squad_lab.SquadLabError as exc:
        raise _bad(exc) from None
    except squad_lab.NotFound:
        raise HTTPException(status_code=404, detail="No such squad.") from None
    db.commit()
    return out


@router.delete("/squads/{squad_id}", status_code=http_status.HTTP_204_NO_CONTENT)
def delete_squad(squad_id: uuid.UUID, db: Session = Depends(get_db), caller: Caller = Depends(require_saving)) -> Response:
    try:
        squad_lab.delete_squad(db, caller, squad_id)
    except squad_lab.NotFound:
        raise HTTPException(status_code=404, detail="No such squad.") from None
    db.commit()
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)
