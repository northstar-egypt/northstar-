"""create squad

A line-up a manager saved in Squad Lab: a formation and which player stands in each slot. It
belongs to the coach's organization; scouts can try line-ups but not save them.

Revision ID: 0010_create_squad
Revises: 0009_create_shortlist_entry
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0010_create_squad"
down_revision: str | None = "0009_create_shortlist_entry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "squad",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("saved_by", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sport", sa.Text(), server_default=sa.text("'football'"), nullable=False),
        sa.Column("formation", sa.Text(), nullable=False),
        sa.Column("slots", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["saved_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_squad_organization_id", "squad", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_squad_organization_id", table_name="squad")
    op.drop_table("squad")
