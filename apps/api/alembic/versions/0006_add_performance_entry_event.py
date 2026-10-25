"""add performance_entry.event

The competition or tournament a record belongs to ("WTT Youth Contender Cairo 2026", "Egyptian
Premier League"). Imported table tennis results name their event, and until now it was shown
in the import preview and then dropped, because the match record had nowhere to keep it.

A core column, not a field in the sport module's metrics: every sport's matches belong to some
competition, and it is not a statistic (the metrics schema admits only defined statistics).
Nullable: a coach logging a friendly, and every existing row, has none.

Revision ID: 0006_add_performance_entry_event
Revises: 0005_add_organization_region
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_add_performance_entry_event"
down_revision: str | None = "0005_add_organization_region"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("performance_entry", sa.Column("event", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("performance_entry", "event")
