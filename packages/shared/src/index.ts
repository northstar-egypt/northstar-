/**
 * NorthStar shared types (TypeScript side).
 *
 * These mirror the shared core defined in docs/schema.md. They are hand-written for now.
 * The Python equivalents live in packages/shared/python/northstar_shared. Keep the two in
 * sync by hand until we add codegen.
 *
 * TODO: replace the hand-written duplication with codegen from a single source of truth
 * (candidate: JSON Schema or Pydantic models) so TS and Python cannot drift.
 */

export type Sport = "football" | "table_tennis";

export type FootballTier = "pro" | "youth" | "diaspora";

export type UserRole =
  | "coach"
  | "scout"
  | "federation"
  | "player"
  | "admin";

export type OrganizationType =
  | "club"
  | "academy"
  | "national_team"
  | "federation";

export type DataSource =
  | "api"
  | "scrape"
  | "coach_logged"
  | "self_submitted"
  | "import";

/** Shared core: the sport-agnostic player identity. See docs/schema.md > Player. */
export interface Player {
  id: string;
  fullName: string;
  knownAs?: string | null;
  dateOfBirth?: string | null; // ISO date
  nationality: string[]; // ISO country codes
  isEgyptEligible: boolean;
  primarySport: Sport;
  tier?: FootballTier | null;
  isMinor: boolean;
}

/**
 * Sport-specific performance payload. The `metrics` object is validated against the
 * per-sport JSON schema in packages/shared/schemas. `schemaRef` records which schema and
 * version validated it, for example "football@1".
 */
export interface PerformanceEntry {
  id: string;
  playerId: string;
  sport: Sport;
  periodType: "match" | "session" | "tournament" | "season_aggregate";
  periodStart: string; // ISO date
  periodEnd?: string | null;
  metrics: Record<string, unknown>;
  schemaRef: string;
  source: DataSource;
  isValidated: boolean;
}
