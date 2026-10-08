"""Request and response shapes for the write endpoints.

Shape checks only: types, lengths, value sets. Anything that needs the database or another
field to decide (is this date before the player was born, is this reading plausible for this
child) is in `app.services.writes`, because a validator here cannot see either.

Two things a client sends are deliberately NOT accepted:

  is_minor   derived from the date of birth on the server. It gates every privacy safeguard
             for children, so it cannot be something a client asserts.
  source,    fixed to coach_logged and the caller. A measurement a human typed in says who
  recorded_by  typed it, and that is not the client's to choose.
"""

from __future__ import annotations

import math
import re
import uuid
from datetime import date

from pydantic import Field, field_validator

from app import sports
from app.models.enums import FootballTier, MeasurementConfidence, PlayerSex
from app.schemas.core import CamelModel, MeasurementOut, PlayerOut

# ISO 3166-1 alpha-2, which is what every row the generator writes already uses. See the
# board item on settling the country code format; this is the one place to change.
_COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")


class MeasurementIn(CamelModel):
    metric: str
    value: float
    unit: str
    confidence: str = MeasurementConfidence.MEASURED.value

    @field_validator("value")
    @classmethod
    def _finite(cls, value: float) -> float:
        # NaN and infinity pass a float check and then poison every average they touch.
        if not math.isfinite(value):
            raise ValueError("must be a finite number")
        return value

    @field_validator("confidence")
    @classmethod
    def _confidence(cls, value: str) -> str:
        allowed = {item.value for item in MeasurementConfidence}
        if value not in allowed:
            raise ValueError(f"must be one of {sorted(allowed)}")
        return value


class MeasurementBatchIn(CamelModel):
    """One visit: everything measured about one player on one day.

    `acknowledge_warnings` is how a coach says "yes, I really measured that". Without it an
    implausible reading is sent back as a question and nothing is saved. With it the reading
    is saved and the acknowledgement is written to the audit log, so the value is kept and it
    did not pass silently.
    """

    measured_at: date
    metrics: list[MeasurementIn] = Field(min_length=1, max_length=10)
    acknowledge_warnings: bool = False


class SignupConsentIn(CamelModel):
    """The sign-up consent form: one signature covering storage, analytics and scouting.

    Joining the platform means signing it, so a player cannot be added without it. For a
    minor the signature is a guardian's and the guardian must be named; for an adult it is
    the player's own and `guardian_name` is ignored. Whether a guardian is needed is decided
    on the server from the date of birth, like `is_minor`.
    """

    signed: bool
    guardian_name: str | None = Field(default=None, max_length=200)

    @field_validator("guardian_name")
    @classmethod
    def _guardian(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None


class PlayerCreateIn(CamelModel):
    full_name: str = Field(min_length=2, max_length=200)
    known_as: str | None = Field(default=None, max_length=100)
    date_of_birth: date
    sex: str | None = None
    nationality: list[str] = Field(default_factory=list, max_length=4)
    is_egypt_eligible: bool = False
    primary_sport: str
    tier: str | None = None
    position: str | None = Field(default=None, max_length=12)
    # Required for an admin, optional for a coach, who always adds to their own. See
    # `access.may_create_player`.
    organization_id: uuid.UUID | None = None
    consent: SignupConsentIn
    # The first visit, saved in the same transaction as the player. Optional, but the add
    # player screen always sends one, and doing it in one request means a failed measurement
    # cannot leave behind a player the coach was told was not saved.
    measurements: MeasurementBatchIn | None = None

    @field_validator("full_name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("must be at least two characters")
        return value

    @field_validator("sex")
    @classmethod
    def _sex(cls, value: str | None) -> str | None:
        allowed = {item.value for item in PlayerSex}
        if value is not None and value not in allowed:
            raise ValueError(f"must be one of {sorted(allowed)}")
        return value

    @field_validator("primary_sport")
    @classmethod
    def _sport(cls, value: str) -> str:
        # The sport modules, not an enum, say which sports exist. See app/sports.py.
        allowed = set(sports.registry())
        if value not in allowed:
            raise ValueError(f"must be one of {sorted(allowed)}")
        return value

    @field_validator("tier")
    @classmethod
    def _tier(cls, value: str | None) -> str | None:
        allowed = {item.value for item in FootballTier}
        if value is not None and value not in allowed:
            raise ValueError(f"must be one of {sorted(allowed)}")
        return value

    @field_validator("nationality")
    @classmethod
    def _nationality(cls, value: list[str]) -> list[str]:
        codes: list[str] = []
        for code in value:
            code = code.strip().upper()
            if not _COUNTRY_CODE.match(code):
                raise ValueError(
                    f"{code!r} is not a two-letter ISO country code, for example EG"
                )
            if code not in codes:
                codes.append(code)
        return codes


class MeasurementWarningOut(CamelModel):
    """Something about a reading that a human should look at before it is saved."""

    metric: str
    value: float
    message: str


class MeasurementsSavedOut(CamelModel):
    measurements: list[MeasurementOut]
    # Warnings the coach acknowledged. Returned so the client can show what was confirmed.
    acknowledged_warnings: list[MeasurementWarningOut] = []


class PlayerCreatedOut(CamelModel):
    player: PlayerOut
    organization_id: uuid.UUID
    measurements: list[MeasurementOut] = []
    acknowledged_warnings: list[MeasurementWarningOut] = []
    # Who signed the sign-up consent: "player" or "guardian:<name>".
    consent_granted_by: str


class ConsentWithdrawalIn(CamelModel):
    """A withdrawal of part of the sign-up consent, recorded on the guardian's behalf.

    `purposes` takes `analytics` and `scouting_visibility`. Withdrawing `data_storage` means
    deleting the record, which is an erasure request with its own flow, so it is refused here.
    For a minor the guardian making the withdrawal must be named, as at sign-up.
    """

    purposes: list[str] = Field(min_length=1, max_length=3)
    guardian_name: str | None = Field(default=None, max_length=200)

    @field_validator("guardian_name")
    @classmethod
    def _guardian(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None


class ConsentWithdrawnOut(CamelModel):
    # Purposes this request ended, and ones that were already not in effect.
    withdrawn: list[str] = []
    already_withdrawn: list[str] = []
    # Who withdrew: "player" or "guardian:<name>".
    withdrawn_by: str
    # Current state per purpose after the withdrawal, as the profile shows it.
    consents: dict[str, bool]
