"""create flag and flag_event

Adds the two tables `docs/wireframes/08-integrity-board.html` argued for, which it called the
largest single gap the wireframing exercise found. Nothing in the original eight tables holds
a raised flag with a type, a confidence, evidence, a status, a reviewer and a decision, so the
integrity board could not be built and the detectors in `ml/` had nowhere to write.

`flag` is what a detector claimed plus the case's current status. `flag_event` is an
append-only history of what happened to it. The rationale for splitting them, and for the
`dedupe_key` that makes a nightly rerun an upsert rather than a duplicate, is in
`app/models/flag.py` and `docs/schema.md`.

Generated with `alembic revision --autogenerate` against the models and then rewritten to
match the conventions of 0001 (stable revision id, explicit column helpers, a downgrade that
drops in dependency-safe order). Verified by re-running autogenerate afterwards, which
produces an empty diff.

Revision ID: 0002_create_flag_tables
Revises: 0001_create_core_tables
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_create_flag_tables"
down_revision: str | None = "0001_create_core_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id_column() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "flag",
        _id_column(),
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        # Null when a rule-based detector has no calibrated probability to offer, which is
        # currently all of them. A null is honest; a fabricated 0.85 is not.
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("detector_name", sa.Text(), nullable=False),
        sa.Column("detector_version", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column(
            "raised_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # The other record in a suspected duplicate pair. Null for every other flag type.
        sa.Column("related_player_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["related_player_id"], ["player.id"], ondelete="SET NULL"),
        # One live case per identity, enforced by the database rather than by the writer
        # remembering to check. This is what stops a nightly detector run handing reviewers
        # the same dismissed false positive every morning.
        sa.UniqueConstraint("dedupe_key", name="uq_flag_dedupe_key"),
    )
    op.create_index("ix_flag_player_id", "flag", ["player_id"])
    # The integrity board's query: open flags, newest first.
    op.create_index("ix_flag_status_raised_at", "flag", ["status", "raised_at"])
    op.create_index("ix_flag_type", "flag", ["type"])

    op.create_table(
        "flag_event",
        _id_column(),
        sa.Column("flag_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Null when the actor was the system, which is every `raised` event.
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        # Insert-only, so no updated_at. A correction is another event.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["flag_id"], ["flag.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_flag_event_flag_id_created_at", "flag_event", ["flag_id", "created_at"]
    )


def downgrade() -> None:
    # Children before parents.
    op.drop_index("ix_flag_event_flag_id_created_at", table_name="flag_event")
    op.drop_table("flag_event")

    op.drop_index("ix_flag_type", table_name="flag")
    op.drop_index("ix_flag_status_raised_at", table_name="flag")
    op.drop_index("ix_flag_player_id", table_name="flag")
    op.drop_table("flag")
