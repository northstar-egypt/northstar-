"""Core entity schemas, mirroring the shared core types in `apps/web/lib/types.ts`.

One rule runs through this file: a response carries only fields the caller is allowed to see,
and the decision about what that is happens in `app.services.access`, not here. Schemas that
make a sensitive field optional are how a field gets withheld, so several things that are
`NOT NULL` in the database are nullable here.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_serializer
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Serialises to camelCase, accepts either case on the way in.

    The frontend is TypeScript and expects camelCase; the database and the ORM are
    snake_case. Converting in one place beats hand-writing an alias on every field
    and then finding the one that was missed at demo time.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


def _decimal_to_float(value: Decimal | float | None) -> float | None:
    """Measurement.value is NUMERIC, which SQLAlchemy hands back as Decimal.

    Decimal does not survive JSON without becoming a string, and the frontend charts do
    arithmetic on these, so they are floats on the wire.
    """
    return float(value) if value is not None else None


class PlayerOut(CamelModel):
    id: uuid.UUID
    full_name: str
    known_as: str | None = None
    date_of_birth: date | None = None
    sex: str | None = None
    nationality: list[str] = []
    is_egypt_eligible: bool = False
    primary_sport: str
    tier: str | None = None
    position: str | None = None
    is_minor: bool = False
    status: str = "active"


class OrganizationOut(CamelModel):
    id: uuid.UUID
    name: str
    type: str
    sport: str | None = None
    country: str
    # Not in the schema. Federation oversight wants coverage by governorate and
    # Organization stores an ISO country code and nothing finer. Raised in
    # docs/wireframes/README.md, still open, so this is always null today.
    region: str | None = None


class MeasurementOut(CamelModel):
    id: uuid.UUID
    player_id: uuid.UUID
    measured_at: date
    metric: str
    value: float
    unit: str
    source: str
    confidence: str | None = None

    @field_serializer("value")
    def _value(self, value: float | Decimal) -> float:
        return float(value)


class PerformanceEntryOut(CamelModel):
    id: uuid.UUID
    player_id: uuid.UUID
    sport: str
    period_type: str
    period_start: date
    period_end: date | None = None
    metrics: dict = {}
    schema_ref: str
    source: str
    is_validated: bool = False


class ConsentOut(CamelModel):
    id: uuid.UUID
    player_id: uuid.UUID
    purpose: str
    granted: bool
    granted_by: str
    guardian_name: str | None = None
    valid_from: date
    valid_until: date | None = None


class SessionUserOut(CamelModel):
    """Who the API believes is calling.

    Served by `/me` so the frontend can stop guessing. Until the security track's auth
    decision lands this is resolved from a development header, and `/me` says so in its
    docstring rather than leaving it to be discovered.
    """

    id: uuid.UUID
    full_name: str
    email: str
    role: str
    organization_id: uuid.UUID | None = None
    organization_name: str | None = None
    linked_player_id: uuid.UUID | None = None
