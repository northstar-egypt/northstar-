"""NorthStar shared types (Python side).

Mirrors packages/shared/src/index.ts. Hand-written for now; keep in sync with the TypeScript
version by hand until codegen replaces the duplication (see this package's README).

Consumed by the API, pipelines, and ML code so every Python component agrees on the shape of
the shared core. The per-sport JSON schemas that validate PerformanceEntry.metrics live in
packages/shared/schemas and are loaded via `schema_path`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Sport = Literal["football", "table_tennis"]
FootballTier = Literal["pro", "youth", "diaspora"]
UserRole = Literal["coach", "scout", "federation", "player", "admin"]
OrganizationType = Literal["club", "academy", "national_team", "federation"]
DataSource = Literal["api", "scrape", "coach_logged", "self_submitted", "import"]

PeriodType = Literal["match", "session", "tournament", "season_aggregate"]

# Directory holding the per-sport JSON validation schemas.
SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"


def schema_path(sport: Sport, version: int = 1) -> Path:
    """Return the path to a sport's JSON validation schema.

    The pipeline validation layer loads this to validate PerformanceEntry.metrics.
    """
    return SCHEMAS_DIR / f"{sport}.schema.json"


@dataclass
class Player:
    """Shared core player identity. See docs/schema.md > Player."""

    id: str
    full_name: str
    nationality: list[str]
    is_egypt_eligible: bool
    primary_sport: Sport
    is_minor: bool
    known_as: str | None = None
    date_of_birth: str | None = None  # ISO date
    tier: FootballTier | None = None


@dataclass
class PerformanceEntry:
    """Sport-specific performance. `metrics` is validated against the sport's JSON schema."""

    id: str
    player_id: str
    sport: Sport
    period_type: PeriodType
    period_start: str  # ISO date
    metrics: dict[str, Any]
    schema_ref: str
    source: DataSource
    is_validated: bool
    period_end: str | None = None
