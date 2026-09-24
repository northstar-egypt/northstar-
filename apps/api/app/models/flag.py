"""Flag and FlagEvent: a claim a model made about a player, and what humans did about it.

This is the table `docs/wireframes/08-integrity-board.html` argued for, and it is the largest
gap the wireframing exercise found. It belongs in the shared core rather than in the ML track
because three workstreams touch it: the ML track writes flags, the application track reads
them, and the security track audits the decisions.

Two tables, not one
-------------------
`Flag` is what a detector claimed, plus the case's current status. `FlagEvent` is an
append-only log of everything that happened to it: raised, confirmed, dismissed, reopened,
commented.

The split is what makes the integrity board's history panel possible. The wireframe requires
history to be visible on the case "so two reviewers do not both work the same flag, and so a
decision can be revisited later with its context intact". A single mutable row cannot do
that; it can only show the most recent decision, and the history would have to be
reconstructed from `AuditLog`, which records that a row changed rather than why a person
decided something.

It also matters for the ML track. Each decision plus its reason is a labelled example, and
labelled examples are what the detectors' precision and recall are computed from. An
append-only log is a training set. An overwritten column is not.

Reruns and `dedupe_key`
-----------------------
A detector that runs nightly will find the same case every night. Without a stable identity
for "this case", a reviewer who dismisses a false positive is handed it again tomorrow, and
with the detectors currently at 0.6 to 0.8 precision that is how a review queue gets
abandoned. `dedupe_key` is that identity: a hash over the player, the flag type, and a coarse
fingerprint of what the evidence was about.

Coarse is the important word. The key deliberately does not include the confidence or the
exact numbers, so ordinary drift does not manufacture a new case. It does include the shape of
the evidence, so a **materially different** observation raises a genuinely new flag rather
than being silently swallowed by an old dismissal. That is the compromise: a dismissal sticks,
but it cannot hide something new.

See `docs/schema.md` for the field list and the open questions this table does not answer,
notably whether a flagged player is told, and who may review a flag against their own
organization.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.player import Player
    from app.models.user import User


class Flag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "flag"

    player_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player.id", ondelete="CASCADE"), nullable=False
    )

    # See enums.FlagType. Text rather than a native enum, matching every other value set in
    # this schema: docs/schema.md leaves the enum question open per column and a native enum
    # makes every future value a migration.
    type: Mapped[str] = mapped_column(Text, nullable=False)

    # See enums.FlagStatus. The only mutable field on this row that matters, and it is
    # derived: every change to it is written alongside a FlagEvent that says who and why.
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'open'")
    )

    # What the model claimed. 0 to 1, null when a rule-based detector has no calibrated
    # probability to offer, which is currently all of them. A null confidence is honest; a
    # fabricated 0.85 is not.
    confidence: Mapped[float | None] = mapped_column(Float)

    # The sentence shown to a reviewer, written for a coach to read. Not optional: the
    # wireframe's rule is that every flag carries the sentence that explains why it fired,
    # and a flag a reviewer cannot understand is one they cannot disagree with.
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    # Structured evidence behind the claim: the measurements, rows or field differences the
    # detector matched on. JSONB because the shape differs per flag type, exactly as
    # PerformanceEntry.metrics differs per sport.
    evidence: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    # Which detector, and which version of it. Without this, a score computed six months from
    # now cannot say which model produced the flags it is scoring.
    detector_name: Mapped[str] = mapped_column(Text, nullable=False)
    detector_version: Mapped[str] = mapped_column(Text, nullable=False)

    # Stable identity for "this case", so a rerun recognises what it has raised before.
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)

    raised_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Set for duplicate flags: the other record in the suspected pair. Null for everything
    # else. A self-referencing pair rather than a cluster table, because every planted
    # duplicate cluster in the dataset is a pair and a cluster table with two members is
    # ceremony.
    related_player_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("player.id", ondelete="SET NULL")
    )

    player: Mapped[Player] = relationship(foreign_keys=[player_id])
    related_player: Mapped[Player | None] = relationship(foreign_keys=[related_player_id])
    events: Mapped[list[FlagEvent]] = relationship(
        back_populates="flag",
        cascade="all, delete-orphan",
        order_by="FlagEvent.created_at",
    )

    __table_args__ = (
        # One live case per identity. This is what makes a rerun an upsert rather than a
        # duplicate, and it is enforced by the database rather than by the writer remembering
        # to check.
        UniqueConstraint("dedupe_key", name="uq_flag_dedupe_key"),
        Index("ix_flag_player_id", "player_id"),
        # The integrity board's query: open flags, newest first.
        Index("ix_flag_status_raised_at", "status", "raised_at"),
        Index("ix_flag_type", "type"),
    )


class FlagEvent(UUIDPrimaryKeyMixin, Base):
    """One thing that happened to a flag. Append-only.

    No `updated_at` and no TimestampMixin: these rows are never modified. A correction is
    another event, which is the point. Deliberately mirrors `AuditLog`, which is also
    insert-only, but lives separately because this is the case's own history shown to
    reviewers rather than a system-wide audit trail.
    """

    __tablename__ = "flag_event"

    flag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("flag.id", ondelete="CASCADE"), nullable=False
    )

    # Null when the actor was the system, which is every `raised` event. The integrity board
    # renders that as "system", matching the wireframe's history table.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL")
    )

    # See enums.FlagAction.
    action: Mapped[str] = mapped_column(Text, nullable=False)

    # Why. Required for a human decision and enforced in the service layer rather than here,
    # because `raised` events have no reason to give. The requirement is not bureaucracy: a
    # decision plus its reason is a labelled example, and labelled examples are what the
    # detectors' precision and recall are computed from.
    reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    flag: Mapped[Flag] = relationship(back_populates="events")
    actor: Mapped[User | None] = relationship()

    __table_args__ = (Index("ix_flag_event_flag_id_created_at", "flag_id", "created_at"),)
