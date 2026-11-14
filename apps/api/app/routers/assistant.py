"""The assistant: a plain-words question, answered from the platform's numbers
(app/services/assistant.py)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import Field
from pydantic.alias_generators import to_camel
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
    # The same results drawn as cards and bars; their shapes are listed at BLOCKS in
    # services/assistant.py. Keys are camelCase like the rest of the response.
    blocks: list[dict[str, Any]] = []
    # Questions to ask next, about the players in this answer.
    follow_ups: list[str] = []
    # "model" when the local language model read the question, "rules" when it was not running
    # (or ASSISTANT_READER=rules) and fixed rules read it (services/rule_reader.py).
    reader: str
    # The model that read it; None when the rules did.
    model: str | None = None


def _camel(value: Any) -> Any:
    if isinstance(value, dict):
        return {to_camel(k): _camel(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_camel(v) for v in value]
    return value


@router.post("/assistant", response_model=AssistantOut)
def ask(
    request: AssistantRequest,
    db: Session = Depends(get_db),
    caller: Caller = Depends(current_user),
) -> AssistantOut:
    """Answer one question as the caller: only what they could open on a screen.

    Never fails for want of the language model: without it the question is read by rule."""
    body = assistant.answer(db, caller, request.question.strip())
    body["blocks"] = _camel(body.get("blocks", []))
    return AssistantOut.model_validate(body)
