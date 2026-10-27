"""create team_season_stat

A team's season in one competition: results, goals and xG for and against, possession, goal
timing, set pieces. Team gap analysis needs it (decision 0003, whose open question this
answers: a table of its own, approved 2026-10-27). PerformanceEntry is a player's record, and a
team row there would need a player that does not exist.

The statistics are a JSON payload validated by the sport module (`teamPeriods`), as players'
are, so a new team statistic is a config change.

Revision ID: 0008_create_team_season_stat
Revises: 0007_add_match_event_details
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008_create_team_season_stat"
down_revision: str | None = "0007_add_match_event_details"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "team_season_stat",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("sport", sa.Text(), nullable=False),
        sa.Column("competition", sa.Text(), nullable=False),
        sa.Column("season", sa.Text(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("schema_ref", sa.Text(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "competition", "season", "schema_ref",
            name="uq_team_season_stat_team_competition_season",
        ),
    )
    op.create_index(
        "ix_team_season_stat_competition_season", "team_season_stat", ["competition", "season"]
    )


def downgrade() -> None:
    op.drop_index("ix_team_season_stat_competition_season", table_name="team_season_stat")
    op.drop_table("team_season_stat")
