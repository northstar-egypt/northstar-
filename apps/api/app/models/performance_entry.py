"""PerformanceEntry: sport-specific performance for a period.

A match, session, tournament, or aggregate window. This is where the JSON sport module lives:
`metrics` is a sport-specific JSONB payload validated against the per-sport schema named by
`schema_ref` (schemas live in packages/shared). See docs/schema.md and CLAUDE.md for the
shared-core-plus-JSON-modules principle: sport-specific metrics belong here, not in new
columns on the core tables.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.player import Player


class PerformanceEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "performance_entry"

    player_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player.id", ondelete="CASCADE")
    )
    # See enums.Sport. Which sport's schema validates `metrics`.
    sport: Mapped[str] = mapped_column(Text)
    # See enums.PeriodType.
    period_type: Mapped[str] = mapped_column(Text)
    period_start: Mapped[date] = mapped_column()
    # Null for a point-in-time event.
    period_end: Mapped[date | None] = mapped_column()
    # The club/academy context, if any.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organization.id", ondelete="SET NULL")
    )
    # For match-type entries.
    opponent_org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organization.id", ondelete="SET NULL")
    )
    # Sport-specific payload, validated against schema_ref on ingest.
    metrics: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Which sport schema + version validated this, e.g. "football@1".
    schema_ref: Mapped[str] = mapped_column(Text)
    # See enums.PerformanceSource.
    source: Mapped[str] = mapped_column(Text)
    # Did it pass the sport schema validation on ingest.
    is_validated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    player: Mapped[Player] = relationship(back_populates="performance_entries")
    organization: Mapped[Organization | None] = relationship(
        foreign_keys=[organization_id]
    )
    opponent_org: Mapped[Organization | None] = relationship(
        foreign_keys=[opponent_org_id]
    )

    __table_args__ = (
        Index("ix_performance_entry_player_period", "player_id", "period_start"),
    )
