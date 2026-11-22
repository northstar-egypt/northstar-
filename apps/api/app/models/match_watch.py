"""MatchWatch: a scout follows an academy player against one professional ("find the next
pro", part 9). The scout is alerted when the style match jumps (app/services/journey.py).
Private to the user, like the shortlist. Migration 0011.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class MatchWatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "match_watch"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("player.id", ondelete="CASCADE"))
    pro_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("player.id", ondelete="CASCADE"))
    # The style match when the user last looked; an alert fires when it has risen enough since.
    last_percent: Mapped[int | None] = mapped_column()

    __table_args__ = (UniqueConstraint("user_id", "player_id", "pro_id", name="uq_match_watch_user_player_pro"),)
