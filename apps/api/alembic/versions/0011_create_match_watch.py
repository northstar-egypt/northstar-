"""create match_watch

"Find the next pro", part 9 (scout alert): a scout follows an academy player against one
professional, and is told when the style match between them jumps. `last_percent` is the match
when the scout last looked. Separate migration so it can be dropped on its own if the feature
is not kept.

Revision ID: 0011_create_match_watch
Revises: 0010_create_drill_log
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_create_match_watch"
down_revision: str | None = "0010_create_drill_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "match_watch",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("pro_id", sa.Uuid(), nullable=False),
        sa.Column("last_percent", sa.Integer(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pro_id"], ["player.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "player_id", "pro_id", name="uq_match_watch_user_player_pro"),
    )
    op.create_index("ix_match_watch_user_id", "match_watch", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_match_watch_user_id", table_name="match_watch")
    op.drop_table("match_watch")
