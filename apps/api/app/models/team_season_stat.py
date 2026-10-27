"""TeamSeasonStat: a team's season in one competition.

What a professional data provider (FootyStats) publishes for a club: results, goals and expected
goals for and against, possession, when goals come, set pieces. Team gap analysis reads it
(decision 0003): where a team is weak against the rest of its league.

The shared-core rule holds as for players (CLAUDE.md): the columns are what every sport's team
season has (which team, which competition and season, when, from where), and the statistics
are a JSON payload validated by the sport module's `teamPeriods`, named by `schema_ref`.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TeamSeasonStat(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "team_season_stat"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE")
    )
    sport: Mapped[str] = mapped_column(Text)
    # The competition's name as published ("Egyptian Premier League") and its season ("2025/26").
    competition: Mapped[str] = mapped_column(Text)
    season: Mapped[str] = mapped_column(Text)
    period_start: Mapped[date] = mapped_column()
    period_end: Mapped[date] = mapped_column()
    # The sport module's team period that validates `metrics`, e.g. "football.team_season.v1".
    schema_ref: Mapped[str] = mapped_column(Text)
    metrics: Mapped[dict] = mapped_column(JSONB)
    # See enums.PerformanceSource: "api" for a data provider's feed.
    source: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "competition", "season", "schema_ref",
            name="uq_team_season_stat_team_competition_season",
        ),
        Index("ix_team_season_stat_competition_season", "competition", "season"),
    )
