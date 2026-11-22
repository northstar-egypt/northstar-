"""Request and response bodies for diaspora submissions (app/routers/submissions.py)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import Field, field_validator

from app.schemas.core import CamelModel
from app.schemas.writes import SignupConsentIn


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


class SubmittedSeasonIn(CamelModel):
    competition: str = Field(min_length=2, max_length=120)
    # "2024/25", or "2025" for a league played in one calendar year.
    season: str = Field(min_length=4, max_length=7)
    # A football.season_basic.v1 record: appearances, minutes, goals, assists, cards.
    metrics: dict


class SubmissionIn(CamelModel):
    full_name: str = Field(min_length=2, max_length=200)
    known_as: str | None = Field(default=None, max_length=100)
    date_of_birth: date
    sex: str | None = None
    nationality: list[str] = Field(default_factory=list, max_length=4)
    eligibility_basis: str
    position: str | None = Field(default=None, max_length=12)
    club_name: str = Field(min_length=2, max_length=200)
    club_country: str = Field(min_length=2, max_length=2)
    competition: str | None = Field(default=None, max_length=120)
    source_url: str = Field(min_length=10, max_length=500)
    note: str = Field(default="", max_length=2000)
    seasons: list[SubmittedSeasonIn] = Field(default_factory=list, max_length=10)
    # The sign-up consent form, when the submitter can record it (app/services/submissions.py,
    # `consent_rule`). Left out, the submission waits for the federation to record it.
    consent: SignupConsentIn | None = None

    _names = field_validator("full_name", "known_as", "club_name", "competition")(_clean)

    @field_validator("nationality")
    @classmethod
    def _codes(cls, value: list[str]) -> list[str]:
        return [code.strip().upper() for code in value if code.strip()]

    @field_validator("club_country")
    @classmethod
    def _country(cls, value: str) -> str:
        return value.strip().upper()


class SubmissionConsentIn(CamelModel):
    """The federation recording the consent form for a submission that waits for it."""

    signed: bool
    guardian_name: str | None = Field(default=None, max_length=200)

    _guardian = field_validator("guardian_name")(_clean)


class SubmissionDecisionIn(CamelModel):
    # approve (a new player), attach (the same person as `player_id`), reject, needs_info.
    action: str
    reason: str = Field(min_length=5, max_length=2000)
    player_id: uuid.UUID | None = None


class SubmissionCheckOut(CamelModel):
    key: str
    label: str
    # clear, attention, refused, not_run, info.
    outcome: str
    summary: str
    matches: list[dict] = []


class SubmissionOut(CamelModel):
    id: uuid.UUID
    status: str
    submitter_role: str
    submitted_by_name: str | None = None
    mine: bool = False
    full_name: str
    known_as: str | None = None
    date_of_birth: date
    is_minor: bool
    sex: str | None = None
    nationality: list[str]
    eligibility_basis: str
    position: str | None = None
    club_name: str
    club_country: str
    competition: str | None = None
    source_url: str
    note: str
    seasons: list[dict]
    consent: dict
    checks: list[SubmissionCheckOut]
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None = None
    review_reason: str | None = None
    player_id: uuid.UUID | None = None


class SubmissionListOut(CamelModel):
    submissions: list[SubmissionOut]


class SubmittedSeasonsOut(CamelModel):
    """GET /players/{id}/submitted-seasons: seasons from approved submissions. Not from a data
    source, and never counted in league analytics (decision 0011)."""

    submissions: list[dict]
    note: str | None = None
