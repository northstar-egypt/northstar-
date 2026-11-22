"""PlayerSubmission: an Egypt-eligible player abroad, submitted for the federation to verify.

Decision 0011. A submission is not a player: nothing here reaches search, the profile's
analytics or the ML until a federation reviewer approves it, and even then its seasons stay on
the submission and are shown on the profile as submitted, never counted in league analytics.
Keeping the claims in their own table is what makes that safe without every query that reads
players having to skip unverified ones.

Who submits: scouts, federation staff and players with an account (themselves). Who reviews:
federation staff, never their own submission. The service is app/services/submissions.py.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PlayerSubmission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "player_submission"

    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), index=True
    )
    # The submitter's role when they submitted: scout, player or federation.
    submitter_role: Mapped[str] = mapped_column(Text)
    # pending, awaiting_consent, needs_info, approved, rejected (SubmissionStatus).
    status: Mapped[str] = mapped_column(Text, index=True)

    # The claims. Football only: the diaspora tier is football's.
    sport: Mapped[str] = mapped_column(Text, server_default=text("'football'"))
    full_name: Mapped[str] = mapped_column(Text)
    known_as: Mapped[str | None] = mapped_column(Text)
    date_of_birth: Mapped[date] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(Text)
    nationality: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    # Why the player could play for Egypt (EligibilityBasis). The reviewer checks it outside the
    # platform and says in the reason what they checked.
    eligibility_basis: Mapped[str] = mapped_column(Text)
    position: Mapped[str | None] = mapped_column(Text)
    club_name: Mapped[str] = mapped_column(Text)
    club_country: Mapped[str] = mapped_column(Text)
    competition: Mapped[str | None] = mapped_column(Text)
    # Where the claims can be checked: a club, league or federation page.
    source_url: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, server_default=text("''"))
    # [{"competition", "season", "metrics"}], each `metrics` a football.season_basic.v1 record.
    seasons: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    # {"signed": bool, "guardianName": str | None, "recordedBy": user id, "on": ISO date}.
    consent: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    # The checks on arrival, rerun on every change (app/services/submissions.py, `run_checks`).
    checks: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))

    # The review.
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(Text)
    # The player record the submission became, or was found to be, on approval.
    player_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("player.id", ondelete="SET NULL"), index=True
    )
