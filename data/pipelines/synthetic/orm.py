"""Access to the API's SQLAlchemy models from the pipeline.

The generators build real ORM instances rather than dictionaries. That is a
deliberate choice and it is the one that catches schema drift: the previous pass
wrote `audit_logs.json` with a key called `metadata`, but `AuditLog` renames that
attribute to `event_metadata` (because `metadata` is reserved on the declarative
Base), so `AuditLog(**row)` raised as soon as anyone tried to load the file. When
the generator constructs the model directly, that mismatch fails at generation
time instead of at load time, and a column renamed in `apps/api` breaks this
pipeline immediately rather than silently.

`apps/api` is not an installed package, so the path bootstrap below locates it
from the repo root. Importing `app.db` constructs an Engine, which does not open
a connection, so this is safe with no database running.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _repo_root() -> Path:
    """Walk up from this file to the directory containing apps/ and data/."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "apps" / "api").is_dir() and (parent / "data").is_dir():
            return parent
    raise RuntimeError(
        "Could not locate the repository root from "
        f"{here}. Run the generator from inside a checkout of the repo."
    )


def _bootstrap() -> None:
    api_dir = _repo_root() / "apps" / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))


_bootstrap()

from app.db import Base  # noqa: E402
from app.models import (  # noqa: E402
    AuditLog,
    Consent,
    Measurement,
    Organization,
    PerformanceEntry,
    Player,
    PlayerOrganization,
    User,
)
from app.models import enums  # noqa: E402

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
    "enums",
]
