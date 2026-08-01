"""Player: the sport-agnostic identity and biometrics record.

One row per real human. Deduplication across sources resolves duplicates to a canonical
Player; a merged record keeps `status = merged` and points at its survivor via `merged_into`.
Biometrics that change over time (height, weight) are NOT columns here; they are Measurement
rows, because tracking them over time is the point. See docs/schema.md.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.consent import Consent
    from app.models.measurement import Measurement
    from app.models.performance_entry import PerformanceEntry
    from app.models.player_organization import PlayerOrganization


class Player(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "player"

    full_name: Mapped[str] = mapped_column(Text)
    known_as: Mapped[str | None] = mapped_column(Text)
    # Null when a source hides it. Drives all age and maturity math.
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    # See enums.PlayerSex. Stored as text; value set not finalized.
    sex: Mapped[str | None] = mapped_column(Text)
    # ISO country codes. Array because diaspora players are dual-national.
    nationality: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    is_egypt_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # See enums.Sport.
    primary_sport: Mapped[str] = mapped_column(Text)
    # See enums.FootballTier. Football tiers; null for other sports.
    tier: Mapped[str | None] = mapped_column(Text)
    # Sport-specific role (e.g. "ST"). Kept as a first-class nullable column because
    # football age curves are per position. Open question in docs/schema.md.
    position: Mapped[str | None] = mapped_column(Text)
    # Derived from date_of_birth. Gates privacy safeguards for minors.
    is_minor: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Source ids, e.g. {"footystats": 123, "transfermarkt": "x"}.
    external_ids: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # See enums.PlayerStatus.
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    # Self-reference. Set when this record was merged into another (the survivor).
    merged_into: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("player.id", ondelete="SET NULL")
    )

    merged_into_player: Mapped[Player | None] = relationship(
        remote_side="Player.id", foreign_keys=[merged_into]
    )
    affiliations: Mapped[list[PlayerOrganization]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )
    measurements: Mapped[list[Measurement]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )
    performance_entries: Mapped[list[PerformanceEntry]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )
    consents: Mapped[list[Consent]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_player_primary_sport", "primary_sport"),
        Index("ix_player_status", "status"),
    )
