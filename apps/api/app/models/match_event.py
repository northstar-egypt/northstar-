"""MatchEvent: one thing a player did in a match, tagged by a coach from match video.

A match record (PerformanceEntry) holds a player's totals for a match: 3 shots, 41 passes.
An event is one of those actions on its own: a shot, from here on the pitch, that went in. A
coach tags them by watching a recording of the match (apps/web/app/(app)/matches/tag). The
video never leaves the coach's computer; only the tags are stored, each with the time in the
video, so a tag can be found again and checked.

The shared-core rule holds (CLAUDE.md, docs/decisions/0005-match-events.md): the columns are
what every sport's events have (who, which match, when in the video, where, what type, what
outcome). Which types and outcomes exist is the sport module's (`events` in
packages/shared/sports/<sport>.json) and is checked when an event is saved, so adding an event
type is a config change.

A match is identified by the club, the date and a short label the coach types ("vs Zamalek
U15"). There is no match table yet; when fixtures are imported (FootyStats), events can point
at one. TODO.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.player import Player


class MatchEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "match_event"

    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("player.id", ondelete="CASCADE"))
    # The club whose coach tagged it. Its coaches may correct or remove it.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organization.id", ondelete="SET NULL")
    )
    # Whose module validates `event_type` and `outcome`.
    sport: Mapped[str] = mapped_column(Text)
    match_date: Mapped[date] = mapped_column()
    # The coach's own name for the match. Free text, short, never a person's details.
    match_label: Mapped[str | None] = mapped_column(Text)
    # From the sport module, for example "shot", and one of that type's outcomes, "goal".
    event_type: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    # Where it happened, 0 to 100 on both axes, on the sport's playing surface: x from the
    # player's own end (0) to the opponent's (100), y from left (0) to right (100) as they face
    # the opponent. In football that is the pitch, goal line to goal line; in table tennis the
    # table, where the ball landed. Null when the coach did not place it.
    x: Mapped[float | None] = mapped_column(Float)
    y: Mapped[float | None] = mapped_column(Float)
    # Seconds into the coach's video, so the tag can be found and checked again.
    video_seconds: Mapped[float | None] = mapped_column(Float)
    # What the coach added after the outcome, {detail: value}: where in the goal, technique,
    # situation, keeper distance; a table tennis stroke. Which details exist is the sport
    # module's (decision 0007). Null when none was added.
    details: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    # See enums.PerformanceSource; "coach_tagged" for everything tagged from video.
    source: Mapped[str] = mapped_column(Text)
    tagged_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL")
    )

    player: Mapped[Player] = relationship(foreign_keys=[player_id])

    __table_args__ = (
        Index("ix_match_event_player_date", "player_id", "match_date"),
        Index("ix_match_event_org_date", "organization_id", "match_date"),
    )
