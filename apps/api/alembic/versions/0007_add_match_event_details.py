"""add match_event.details

What a coach adds to a tagged event after its outcome: where in the goal a shot went, its
technique, whether it was a one-on-one and how far away the keeper was; the stroke that won or
lost a table tennis point. Decision 0007.

A JSON field and not columns, by the shared-core rule (CLAUDE.md): which details exist, and
their values, are the sport module's (`events.types.<type>.details` in
packages/shared/sports/<sport>.json), checked when a tag is saved, so a new detail is a config
change. Nullable: a tag needs none, and every existing row has none.

Revision ID: 0007_add_match_event_details
Revises: 0006_add_performance_entry_event
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007_add_match_event_details"
down_revision: str | None = "0006_add_performance_entry_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("match_event", sa.Column("details", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("match_event", "details")
