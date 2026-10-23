"""create match_event

One row per thing a player did in a match, tagged by a coach from match video: a shot, a
pass, a tackle, with its outcome, where on the pitch it was, and the time in the video. Event
types and outcomes come from the sport module, so the table holds only what every sport's
events share. The reasoning and the alternatives (a list inside the match record's JSON) are
in docs/decisions/0005-match-events.md.

Index and foreign key names are the ones Postgres and the model produce, so running
autogenerate after this migration gives an empty diff.

Revision ID: 0004_create_match_event
Revises: 0003_add_opponent_player
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_create_match_event"
down_revision: str | None = "0003_add_opponent_player"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "match_event",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sport", sa.Text(), nullable=False),
        sa.Column("match_date", sa.Date(), nullable=False),
        sa.Column("match_label", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("x", sa.Float(), nullable=True),
        sa.Column("y", sa.Float(), nullable=True),
        sa.Column("video_seconds", sa.Float(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("tagged_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tagged_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_match_event_player_date", "match_event", ["player_id", "match_date"])
    op.create_index("ix_match_event_org_date", "match_event", ["organization_id", "match_date"])


def downgrade() -> None:
    op.drop_index("ix_match_event_org_date", table_name="match_event")
    op.drop_index("ix_match_event_player_date", table_name="match_event")
    op.drop_table("match_event")
