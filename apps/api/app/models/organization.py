"""Organization: any club, academy, national team, or federation.

Self-referencing so an academy can belong to a club and a club can sit under a federation.
See docs/schema.md.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.player_organization import PlayerOrganization
    from app.models.user import User


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization"

    name: Mapped[str] = mapped_column(Text)
    # See enums.OrganizationType.
    type: Mapped[str] = mapped_column(Text)
    # See enums.Sport. Null for multi-sport bodies.
    sport: Mapped[str | None] = mapped_column(Text)
    # ISO country code.
    country: Mapped[str] = mapped_column(Text)
    parent_org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organization.id", ondelete="SET NULL")
    )
    external_ids: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    parent: Mapped[Organization | None] = relationship(
        remote_side="Organization.id", back_populates="children"
    )
    children: Mapped[list[Organization]] = relationship(back_populates="parent")
    memberships: Mapped[list[PlayerOrganization]] = relationship(
        back_populates="organization"
    )
    users: Mapped[list[User]] = relationship(back_populates="organization")
