"""NorthStar shared types (Python side).

Mirrors packages/shared/src/index.ts. Hand-written for now; keep in sync with the TypeScript
version by hand until codegen replaces the duplication (see this package's README).

Consumed by the API, pipelines, and ML code so every Python component agrees on the shape of
the shared core. The sport modules that validate PerformanceEntry.metrics live in
packages/shared/sports; `apps/api/app/sports.py` loads and validates them.
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

# Directory holding the sport modules. See packages/shared/README.md.
SPORTS_DIR = Path(__file__).resolve().parents[2] / "sports"


def sport_module_path(sport: str) -> Path:
    """Return the path to a sport's module file."""
    return SPORTS_DIR / f"{sport}.json"


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
    """Sport-specific performance. `metrics` is validated by the sport module for `schema_ref`."""

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
