"""Consent: consent and privacy records, first-class because much youth data is about minors.

One player can have multiple consent records over time and per purpose. The application must
check the relevant consent before exposing a minor's profile to scouts; that enforcement is an
access-control concern, and this table is the record it reads. See docs/schema.md and CLAUDE.md
(minors' privacy is first-class, not an afterthought).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.player import Player


class Consent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "consent"

    player_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player.id", ondelete="CASCADE")
    )
    # See enums.ConsentPurpose, e.g. data_storage / analytics / scouting_visibility.
    purpose: Mapped[str] = mapped_column(Text)
    # Current state for this purpose.
    granted: Mapped[bool] = mapped_column(Boolean)
    # Who consented: the player, or a guardian for a minor.
    granted_by: Mapped[str] = mapped_column(Text)
    # Required when the player is a minor. TODO (security): enforce at the app layer.
    guardian_name: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date] = mapped_column()
    # Null means open-ended.
    valid_until: Mapped[date | None] = mapped_column()
    # Pointer to a stored consent document, if any.
    document_ref: Mapped[str | None] = mapped_column(Text)

    player: Mapped[Player] = relationship(back_populates="consents")

    __table_args__ = (
        Index("ix_consent_player_id", "player_id"),
    )
