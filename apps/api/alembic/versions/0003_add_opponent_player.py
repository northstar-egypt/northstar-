"""add performance_entry.opponent_player_id

A match in a one-on-one sport is against a player, not a club. Until now the only opponent
field was `opponent_org_id`, so a table tennis result could not say who it was against, and
nothing could tell a win over a beginner from a win over the national number one. This column
names the opponent when they are registered on the platform. When they are not, it stays null
and nothing about them is stored: they may be a child with no signed consent form.

It is a core column rather than a field in the sport module's JSON because every one-on-one
sport has it (tennis, badminton, squash, judo), and because it is a reference to another
player, which must stay correct when that player is deleted (SET NULL) or merged. The
reasoning, and the alternatives, are in docs/decisions/0004-table-tennis-opponent-strength.md.

The foreign key and index names are the ones Postgres and the model produce, so running
autogenerate after this migration gives an empty diff.

Revision ID: 0003_add_opponent_player
Revises: 0002_create_flag_tables
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_add_opponent_player"
down_revision: str | None = "0002_create_flag_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "performance_entry",
        sa.Column("opponent_player_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "performance_entry_opponent_player_id_fkey",
        "performance_entry",
        "player",
        ["opponent_player_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_performance_entry_opponent_player",
        "performance_entry",
        ["opponent_player_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_performance_entry_opponent_player", table_name="performance_entry")
    op.drop_constraint(
        "performance_entry_opponent_player_id_fkey", "performance_entry", type_="foreignkey"
    )
    op.drop_column("performance_entry", "opponent_player_id")
