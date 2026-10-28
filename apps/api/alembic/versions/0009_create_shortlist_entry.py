"""create shortlist_entry

A player a scout or federation staff member saved, with their own note. The scout's home page
opens with it (the role homes work: each role lands on what its job needs). One row per user and
player; the user's list is private to them.

Revision ID: 0009_create_shortlist_entry
Revises: 0008_create_team_season_stat
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_create_shortlist_entry"
down_revision: str | None = "0008_create_team_season_stat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shortlist_entry",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "player_id", name="uq_shortlist_entry_user_player"),
    )
    op.create_index("ix_shortlist_entry_user_id", "shortlist_entry", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_shortlist_entry_user_id", table_name="shortlist_entry")
    op.drop_table("shortlist_entry")
