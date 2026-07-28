"""PlayerOrganization: the player-to-organization affiliation history.

The many-to-many link between players and organizations over time. A player moves between
academies and clubs; this table is the history of those affiliations. See docs/schema.md.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.player import Player


class PlayerOrganization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "player_organization"

    player_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player.id", ondelete="CASCADE")
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE")
    )
    # See enums.PlayerOrganizationRole.
    role: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column()
    # Null means the affiliation is current.
    end_date: Mapped[date | None] = mapped_column()
    shirt_number: Mapped[int | None] = mapped_column(Integer)

    player: Mapped[Player] = relationship(back_populates="affiliations")
    organization: Mapped[Organization] = relationship(back_populates="memberships")

    # TODO (data engineering): the schema wants "no two overlapping active affiliations of the
    # same role for one player at one org". That needs an exclusion constraint (btree_gist);
    # left as a follow-up. For now, index the common lookup axes.
    __table_args__ = (
        Index("ix_player_organization_player_id", "player_id"),
        Index("ix_player_organization_organization_id", "organization_id"),
    )
