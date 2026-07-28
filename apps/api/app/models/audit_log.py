"""AuditLog: append-only record of who did what.

Feeds both the security workstream (accountability) and the integrity board (surfacing
suspicious activity). Append-only is a rule, not a suggestion: no UPDATE, no DELETE. There is
deliberately no updated_at (nothing is ever updated) and no TimestampMixin; created_at is the
query axis and is indexed. TODO (security): enforce append-only with a trigger or permissions.
See docs/schema.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_log"

    # Who did it. Null for system actions.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL")
    )
    # For example player.update, login.success, search.run.
    action: Mapped[str] = mapped_column(Text)
    # For example Player, PerformanceEntry.
    entity_type: Mapped[str | None] = mapped_column(Text)
    # The affected row.
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Before/after diff, request context, flags raised. Mapped to the "metadata" column;
    # the Python attribute is renamed because "metadata" is reserved on declarative Base.
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)
    ip_address: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    actor: Mapped[User | None] = relationship(back_populates="audit_logs")

    __table_args__ = (
        # created_at is the primary query axis; entity lookups are the other common one.
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )
