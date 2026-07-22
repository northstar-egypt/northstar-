"""ORM models for the shared core schema.

Import every model module here so that Alembic autogenerate and metadata creation see them.
The concrete tables from docs/schema.md (Player, Organization, Measurement,
PerformanceEntry, User, Consent, AuditLog) are implemented by the data-engineering
workstream. This file wires them into Base.metadata once they exist.
"""

from app.db import Base  # noqa: F401  (re-exported so Alembic env can import metadata)

# TODO (data engineering): import model modules here as they are added, e.g.
#   from app.models import player, organization, measurement, performance_entry
# Each import must run so the table is registered on Base.metadata before migrations.
