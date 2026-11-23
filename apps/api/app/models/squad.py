"""Squad: a line-up a manager saved in Squad Lab.

A squad belongs to the coach's organization, so every coach at the club sees and edits the
same plans. Scouts and federation staff can try line-ups in Squad Lab but cannot save one,
and they never see a club's saved squads: a manager's plans for the weekend are the club's.

`slots` maps a formation slot id ("LCB") to a player id. Saving a squad does not widen what
anyone may see. Every read goes through `access.may_view`, so a player who has left the club
since the squad was saved comes back as an unavailable slot rather than a name.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Squad(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "squad"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )
    # Who saved it last. Kept when the account is removed, so the squad survives.
    saved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(Text)
    sport: Mapped[str] = mapped_column(Text, server_default=text("'football'"))
    # A key of `squadLab.formations` in the sport module, e.g. "4-3-3".
    formation: Mapped[str] = mapped_column(Text)
    slots: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
