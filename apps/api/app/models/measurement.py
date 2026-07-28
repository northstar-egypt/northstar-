"""Measurement: sport-agnostic time-series of things measured about a player.

Biometrics and physical tests, long-format (one row per player per metric per date), which
makes growth curves and maturity math straightforward. Long-format instead of wide columns so
a new physical test is data, not a migration. See docs/schema.md.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.player import Player
    from app.models.user import User


class Measurement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "measurement"

    player_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player.id", ondelete="CASCADE")
    )
    measured_at: Mapped[date] = mapped_column()
    # Controlled vocabulary, e.g. height_cm / weight_kg / sprint_10m_s.
    metric: Mapped[str] = mapped_column(Text)
    value: Mapped[Decimal] = mapped_column(Numeric)
    # Stored explicitly to avoid unit ambiguity.
    unit: Mapped[str] = mapped_column(Text)
    # See enums.MeasurementSource.
    source: Mapped[str] = mapped_column(Text)
    # To User, when a human entered it. Null for automated ingest.
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL")
    )
    # See enums.MeasurementConfidence. Maturity models care about measured vs estimated.
    confidence: Mapped[str | None] = mapped_column(Text)

    player: Mapped[Player] = relationship(back_populates="measurements")
    recorded_by_user: Mapped[User | None] = relationship()

    __table_args__ = (
        # Growth curves query by player + metric over time.
        Index("ix_measurement_player_metric_date", "player_id", "metric", "measured_at"),
    )
