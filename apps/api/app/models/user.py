"""User: an account that logs into the platform.

Distinct from Player: a player may or may not have a user account, and most users (coaches,
scouts, federation staff) are not players. `role` is the anchor of the access-control
workstream. See docs/schema.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.audit_log import AuditLog
    from app.models.organization import Organization
    from app.models.player import Player


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user"

    # Case-insensitive uniqueness is enforced by a functional unique index on lower(email)
    # below. The schema calls for citext; a lower() index gives the same guarantee without a
    # citext extension dependency. TODO (security): revisit if we adopt citext project-wide.
    email: Mapped[str] = mapped_column(Text)
    # Hashed only, never plaintext. TODO (security): hashing choice (argon2/bcrypt).
    password_hash: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text)
    # See enums.UserRole.
    role: Mapped[str] = mapped_column(Text)
    # The org this user belongs to. Scopes what they can see.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organization.id", ondelete="SET NULL")
    )
    # Set when the user is also a player (self-submission, own profile).
    linked_player_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("player.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped[Organization | None] = relationship(back_populates="users")
    linked_player: Mapped[Player | None] = relationship()
    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates="actor")

    __table_args__ = (
        Index("ix_user_email_lower", text("lower(email)"), unique=True),
    )
