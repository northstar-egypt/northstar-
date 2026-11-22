"""DrillLog: a drill a youth player did ("find the next pro", parts 6 to 8).

Logged by the player's coach or by the player. Counted in the weekly report and as XP in the
game journey and the academy leaderboard (app/services/journey.py). Migration 0010.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class DrillLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "drill_log"

    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("player.id", ondelete="CASCADE"))
    logged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    done_on: Mapped[date] = mapped_column()
    # The weak statistic the drill works on (a key of `weakPoints.drills` in the sport module).
    statistic: Mapped[str] = mapped_column(Text)
    drill: Mapped[str] = mapped_column(Text)

    __table_args__ = (Index("ix_drill_log_player_id_done_on", "player_id", "done_on"),)
