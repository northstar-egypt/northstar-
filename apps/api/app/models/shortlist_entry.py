"""ShortlistEntry: a player a scout (or federation staff member) is keeping an eye on.

The scout's home opens with it: the players they saved, each with their own note. It belongs
to the user, not to an organization: one scout's shortlist is not shown to anyone else.

Saving a player does not widen what the user may see. The list is read through the same rule
as every other screen (`access.may_view`), so a player whose consent is withdrawn after being
saved is counted as withheld rather than shown.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ShortlistEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "shortlist_entry"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("player.id", ondelete="CASCADE"))
    # The user's own words: why this player, what to watch for. Empty is fine.
    note: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (UniqueConstraint("user_id", "player_id", name="uq_shortlist_entry_user_player"),)
