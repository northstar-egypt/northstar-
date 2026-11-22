"""create player_submission

An Egypt-eligible player abroad, submitted by a scout, federation staff or the player, for the
federation to verify (decision 0011). Kept apart from `player` until approved, so no
unverified record reaches search or analytics.

Revision ID: 0010_create_player_submission
Revises: 0009_create_shortlist_entry
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0010_create_player_submission"
down_revision: str | None = "0009_create_shortlist_entry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "player_submission",
        sa.Column("submitted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("submitter_role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("sport", sa.Text(), server_default=sa.text("'football'"), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("known_as", sa.Text(), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("sex", sa.Text(), nullable=True),
        sa.Column("nationality", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("eligibility_basis", sa.Text(), nullable=False),
        sa.Column("position", sa.Text(), nullable=True),
        sa.Column("club_name", sa.Text(), nullable=False),
        sa.Column("club_country", sa.Text(), nullable=False),
        sa.Column("competition", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("seasons", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("consent", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("checks", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("player_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_player_submission_submitted_by_user_id", "player_submission", ["submitted_by_user_id"])
    op.create_index("ix_player_submission_status", "player_submission", ["status"])
    op.create_index("ix_player_submission_player_id", "player_submission", ["player_id"])


def downgrade() -> None:
    op.drop_index("ix_player_submission_player_id", table_name="player_submission")
    op.drop_index("ix_player_submission_status", table_name="player_submission")
    op.drop_index("ix_player_submission_submitted_by_user_id", table_name="player_submission")
    op.drop_table("player_submission")
