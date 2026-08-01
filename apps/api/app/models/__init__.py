"""ORM models for the shared core schema.

Every model module is imported here so that Alembic autogenerate and metadata creation see
the full set of tables on Base.metadata. The concrete tables come from docs/schema.md
(shared core + JSON sport modules; see CLAUDE.md).

Import order matters only in that all models must be imported before the mapper is configured;
relationships use string references, so the modules themselves can be listed in any order.
"""

from app.db import Base  # noqa: F401  (re-exported so Alembic env can import metadata)
from app.models.audit_log import AuditLog
from app.models.consent import Consent
from app.models.measurement import Measurement
from app.models.organization import Organization
from app.models.performance_entry import PerformanceEntry
from app.models.player import Player
from app.models.player_organization import PlayerOrganization
from app.models.user import User

__all__ = [
    "Base",
    "AuditLog",
    "Consent",
    "Measurement",
    "Organization",
    "PerformanceEntry",
    "Player",
    "PlayerOrganization",
    "User",
]
