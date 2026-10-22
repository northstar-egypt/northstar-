"""The assistant: a plain-words question, answered from the platform's numbers
(app/services/assistant.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.schemas.core import CamelModel
from app.services import assistant
from app.services.access import Caller

router = APIRouter(tags=["assistant"])


class AssistantRequest(CamelModel):
    question: str = Field(min_length=2, max_length=300)


class AssistantReadingOut(CamelModel):
    intent: str
    sport: str | None = None
    gender: str | None = None
    position_group: str | None = None
    age_from: int | None = None
    age_to: int | None = None
    statistic: str | None = None
    players: list[str] = []


class AssistantRowOut(CamelModel):
    # Set when the first cell is a player the caller may open, so the screen can link it.
    player_id: str | None = None
    cells: list[str]


class AssistantLinkOut(CamelModel):
    label: str
    href: str


class AssistantOut(CamelModel):
    question: str
    # What the model read, as a form and in words. The screen prints the words.
    reading: AssistantReadingOut
    chips: list[str] = []
    # Built from the services' results. No number in it was written by the model.
    answer: str
    columns: list[str] = []
    rows: list[AssistantRowOut] = []
    # The screen that shows the same thing, where the reading can be corrected by hand.
    link: AssistantLinkOut | None = None
    note: str = ""
    model: str


@router.post("/assistant", response_model=AssistantOut)
def ask(
    request: AssistantRequest,
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> AssistantOut:
    """Answer one question as the caller: only what they could open on a screen."""
    try:
        body = assistant.answer(db, caller, request.question.strip())
    except assistant.OllamaUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from None
    return AssistantOut.model_validate(body)
