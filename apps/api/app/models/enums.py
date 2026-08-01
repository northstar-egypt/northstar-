"""Controlled value sets for the core schema.

docs/schema.md leaves "Postgres enum vs lookup table vs plain string" as an open question
per enum, and notes that several value sets are not finalized. To avoid locking the database
into values that will change (every change to a native Postgres enum or CHECK constraint is a
migration), the model columns are plain string/text for now. These `StrEnum` classes are the
single reference for the intended values, used by the application and pipeline validation
layers. When the team settles the value sets, we can promote the hot ones to a DB constraint.

TODO (data engineering + security): confirm final value sets at the first meeting, then
decide which of these become native Postgres enums or lookup tables.
"""

from enum import StrEnum


class PlayerSex(StrEnum):
    MALE = "male"
    FEMALE = "female"


class Sport(StrEnum):
    FOOTBALL = "football"
    TABLE_TENNIS = "table_tennis"


class FootballTier(StrEnum):
    PRO = "pro"
    YOUTH = "youth"
    DIASPORA = "diaspora"


class PlayerStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    MERGED = "merged"


class OrganizationType(StrEnum):
    CLUB = "club"
    ACADEMY = "academy"
    NATIONAL_TEAM = "national_team"
    FEDERATION = "federation"


class PlayerOrganizationRole(StrEnum):
    PLAYER = "player"
    YOUTH_PROSPECT = "youth_prospect"
    TRIALIST = "trialist"


class MeasurementSource(StrEnum):
    COACH_LOGGED = "coach_logged"
    SELF_SUBMITTED = "self_submitted"
    IMPORT = "import"
    API = "api"


class MeasurementConfidence(StrEnum):
    MEASURED = "measured"
    ESTIMATED = "estimated"


class PeriodType(StrEnum):
    MATCH = "match"
    SESSION = "session"
    TOURNAMENT = "tournament"
    SEASON_AGGREGATE = "season_aggregate"


class PerformanceSource(StrEnum):
    API = "api"
    SCRAPE = "scrape"
    COACH_LOGGED = "coach_logged"
    SELF_SUBMITTED = "self_submitted"
    IMPORT = "import"


class UserRole(StrEnum):
    COACH = "coach"
    SCOUT = "scout"
    FEDERATION = "federation"
    PLAYER = "player"
    ADMIN = "admin"


class ConsentPurpose(StrEnum):
    DATA_STORAGE = "data_storage"
    ANALYTICS = "analytics"
    SCOUTING_VISIBILITY = "scouting_visibility"
