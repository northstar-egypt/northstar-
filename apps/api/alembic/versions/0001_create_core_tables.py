"""create core tables

Creates the eight shared-core tables from docs/schema.md: organization, player, user,
player_organization, measurement, performance_entry, consent, audit_log.

This migration was written by hand to match the ORM models in app/models (validated by
rendering the models to PostgreSQL DDL). It is the equivalent of the first
`alembic revision --autogenerate`. Sport-specific performance data lives in the JSONB
`performance_entry.metrics` column, not in new columns (see CLAUDE.md).

Notes:
- UUID primary keys default to `gen_random_uuid()`, built into PostgreSQL 13+ (the stack runs
  Postgres 16), so no extension is required.
- User email uniqueness is a functional unique index on `lower(email)`, giving
  case-insensitive uniqueness without a citext dependency.

Revision ID: 0001_create_core_tables
Revises:
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_create_core_tables"
down_revision: str | None = None
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
    # organization: self-referencing hierarchy of clubs, academies, national teams, federations.
    op.create_table(
        "organization",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("sport", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=False),
        sa.Column("parent_org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "external_ids",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        _id_column(),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["parent_org_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # player: sport-agnostic identity and biometrics. Self-ref merged_into for dedup survivors.
    op.create_table(
        "player",
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("known_as", sa.Text(), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("sex", sa.Text(), nullable=True),
        sa.Column(
            "nationality",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "is_egypt_eligible",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("primary_sport", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=True),
        sa.Column("position", sa.Text(), nullable=True),
        sa.Column(
            "is_minor", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "external_ids",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column("merged_into", postgresql.UUID(as_uuid=True), nullable=True),
        _id_column(),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["merged_into"], ["player.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_player_primary_sport", "player", ["primary_sport"])
    op.create_index("ix_player_status", "player", ["status"])

    # user: platform accounts. role anchors the access-control workstream.
    op.create_table(
        "user",
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("linked_player_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        _id_column(),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["linked_player_id"], ["player.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Case-insensitive uniqueness without a citext dependency.
    op.create_index(
        "ix_user_email_lower", "user", [sa.text("lower(email)")], unique=True
    )

    # player_organization: affiliation history (player <-> organization over time).
    op.create_table(
        "player_organization",
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("shirt_number", sa.Integer(), nullable=True),
        _id_column(),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_player_organization_player_id", "player_organization", ["player_id"]
    )
    op.create_index(
        "ix_player_organization_organization_id",
        "player_organization",
        ["organization_id"],
    )

    # measurement: long-format time-series of biometrics and physical tests.
    op.create_table(
        "measurement",
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("measured_at", sa.Date(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confidence", sa.Text(), nullable=True),
        _id_column(),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_measurement_player_metric_date",
        "measurement",
        ["player_id", "metric", "measured_at"],
    )

    # performance_entry: sport-specific performance. The JSON sport module lives in `metrics`.
    op.create_table(
        "performance_entry",
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sport", sa.Text(), nullable=False),
        sa.Column("period_type", sa.Text(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("opponent_org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "metrics",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("schema_ref", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "is_validated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        _id_column(),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["opponent_org_id"], ["organization.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_performance_entry_player_period",
        "performance_entry",
        ["player_id", "period_start"],
    )

    # consent: privacy records, first-class because much youth data is about minors.
    op.create_table(
        "consent",
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("granted_by", sa.Text(), nullable=False),
        sa.Column("guardian_name", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("document_ref", sa.Text(), nullable=True),
        _id_column(),
        *_timestamp_columns(),
        sa.ForeignKeyConstraint(["player_id"], ["player.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_consent_player_id", "consent", ["player_id"])

    # audit_log: append-only. No updated_at by design; created_at is the query axis.
    op.create_table(
        "audit_log",
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _id_column(),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index(
        "ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"]
    )


def downgrade() -> None:
    # Reverse of upgrade: drop in dependency-safe order (children before parents).
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index("ix_consent_player_id", table_name="consent")
    op.drop_table("consent")

    op.drop_index(
        "ix_performance_entry_player_period", table_name="performance_entry"
    )
    op.drop_table("performance_entry")

    op.drop_index("ix_measurement_player_metric_date", table_name="measurement")
    op.drop_table("measurement")

    op.drop_index(
        "ix_player_organization_organization_id", table_name="player_organization"
    )
    op.drop_index(
        "ix_player_organization_player_id", table_name="player_organization"
    )
    op.drop_table("player_organization")

    op.drop_index("ix_user_email_lower", table_name="user")
    op.drop_table("user")

    op.drop_index("ix_player_status", table_name="player")
    op.drop_index("ix_player_primary_sport", table_name="player")
    op.drop_table("player")

    op.drop_table("organization")
