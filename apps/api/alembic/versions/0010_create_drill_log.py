"""create drill_log

"Find the next pro", parts 6 to 8 (weekly report, game journey, leaderboard): a drill a youth
player did, logged by their coach or by the player. Drills done count in the weekly report and
earn XP. Separate migration so it can be dropped on its own if the feature is not kept.

Revision ID: 0010_create_drill_log
Revises: 0009_create_shortlist_entry
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_create_drill_log"
down_revision: str | None = "0009_create_shortlist_entry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "drill_log",
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("logged_by", sa.Uuid(), nullable=True),
        sa.Column("done_on", sa.Date(), nullable=False),
        sa.Column("statistic", sa.Text(), nullable=False),
        sa.Column("drill", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["logged_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_drill_log_player_id_done_on", "drill_log", ["player_id", "done_on"])


def downgrade() -> None:
    op.drop_index("ix_drill_log_player_id_done_on", table_name="drill_log")
    op.drop_table("drill_log")
