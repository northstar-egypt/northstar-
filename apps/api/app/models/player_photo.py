"""PlayerPhoto: a photo a manager uploaded for one of his adult players, for Squad Lab cards.

Adults only. Many players are children, and the guardian's sign-up form covers storage,
analytics and scouting visibility, not photos, so the API refuses a photo of a minor and stops
serving one if the player is recorded as a minor later.

The image lives in this table, never in the repository or on disk next to the code. One photo
per player; uploading again replaces it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, LargeBinary, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin


class PlayerPhoto(TimestampMixin, Base):
    __tablename__ = "player_photo"

    player_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("player.id", ondelete="CASCADE"), primary_key=True
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    # One of image/jpeg, image/png, image/webp, checked against the file's first bytes.
    content_type: Mapped[str] = mapped_column(Text)
    data: Mapped[bytes] = mapped_column(LargeBinary)
