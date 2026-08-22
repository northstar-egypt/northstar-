/**
 * Types the web app works with.
 *
 * The shared core types mirror `packages/shared/src/index.ts`, which mirrors
 * `docs/schema.md`. They are duplicated here rather than imported because the shared package
 * has no build step yet and the repo README notes codegen as a TODO. When that lands, delete
 * the duplicated core types below and import them instead.
 *
 * The view model types further down have no equivalent in the schema. They are shapes the
 * screens need, assembled by the API from several tables plus the ML layer's output. They are
 * written here as a proposal for what the endpoints should return, so the application and data
 * tracks have something concrete to agree on.
 */

/* ------------------------------------------------------------------ shared core */

export type Sport = "football" | "table_tennis";
export type FootballTier = "pro" | "youth" | "diaspora";
export type UserRole = "coach" | "scout" | "federation" | "player" | "admin";
export type OrganizationType = "club" | "academy" | "national_team" | "federation";
export type DataSource = "api" | "scrape" | "coach_logged" | "self_submitted" | "import";
export type MeasurementConfidence = "measured" | "estimated";

export interface Player {
  id: string;
  fullName: string;
  knownAs?: string | null;
  dateOfBirth?: string | null;
  sex?: "male" | "female" | null;
  nationality: string[];
  isEgyptEligible: boolean;
  primarySport: Sport;
  tier?: FootballTier | null;
  position?: string | null;
  isMinor: boolean;
  status: "active" | "archived" | "merged";
}

export interface Organization {
  id: string;
  name: string;
  type: OrganizationType;
  sport?: Sport | null;
  country: string;
  /**
   * Not in the schema today. Federation oversight needs coverage by governorate and
   * `Organization` stores an ISO country code and nothing finer. Raised in
   * `docs/wireframes/README.md`. Optional here so the screens can be built while the data
   * track decides.
   */
  region?: string | null;
}

export interface Measurement {
  id: string;
  playerId: string;
  measuredAt: string;
  metric: string;
  value: number;
  unit: string;
  source: DataSource;
  confidence?: MeasurementConfidence | null;
}

export interface PerformanceEntry {
  id: string;
  playerId: string;
  sport: Sport;
  periodType: "match" | "session" | "tournament" | "season_aggregate";
  periodStart: string;
  periodEnd?: string | null;
  metrics: Record<string, number>;
  schemaRef: string;
  source: DataSource;
  isValidated: boolean;
}

export interface Consent {
  id: string;
  playerId: string;
  purpose: "data_storage" | "analytics" | "scouting_visibility";
  granted: boolean;
  grantedBy: string;
  guardianName?: string | null;
  validFrom: string;
  validUntil?: string | null;
}

export interface SessionUser {
  id: string;
  fullName: string;
  email: string;
  role: UserRole;
  organizationId: string | null;
  organizationName: string | null;
  linkedPlayerId?: string | null;
}

/* ------------------------------------------------- view models, assembled by the API */

/** One row in the coach's squad table. Aggregates that must not be computed client side. */
export interface SquadRow {
  player: Player;
  ageLabel: string;
  heightCm: number | null;
  daysSinceLastLog: number | null;
  /** Last six height readings, oldest first, for the sparkline. */
  heightTrend: number[];
  flags: FlagSummary[];
  consentComplete: boolean;
}

export interface FlagSummary {
  type: "late_bloomer" | "breakout" | "fraud" | "duplicate" | "anomaly" | "consent";
  label: string;
  confidence?: number | null;
}

/** A forecast point. The band is what makes it honest, so it is not optional. */
export interface ForecastPoint {
  date: string;
  value: number;
  lower: number;
  upper: number;
}

export interface GrowthSeries {
  measured: { date: string; value: number }[];
  forecast: ForecastPoint[];
  /** Population reference band for this age and sex, drawn behind the player's line. */
  population: { date: string; p25: number; p50: number; p75: number }[];
  unit: string;
}

export interface Percentile {
  metric: string;
  label: string;
  value: number;
  unit: string;
  percentile: number;
  /** Stated population. A percentile without one is meaningless. */
  population: string;
  /** False for metrics where a lower number is better, such as sprint time. */
  higherIsBetter: boolean;
}

export interface MaturityEstimate {
  /** Negative means behind peers, which is the late bloomer signal. */
  offsetYears: number;
  predictedAdultHeightCm: number;
  errorCm: number;
  method: string;
}

export interface PlayerProfile {
  player: Player;
  organizationName: string | null;
  ageLabel: string;
  latest: { heightCm: number | null; weightKg: number | null };
  growth: GrowthSeries;
  maturity: MaturityEstimate | null;
  percentiles: Percentile[];
  performance: PerformanceEntry[];
  flags: FlagSummary[];
  flagReason: string | null;
  summary: string | null;
  provenance: {
    measurementCount: number;
    performanceCount: number;
    consents: { purpose: string; granted: boolean }[];
  };
  /** What the current role is permitted to do, decided by the API, not by the frontend. */
  permissions: { canEdit: boolean; canLog: boolean; canSeeFlags: boolean };
}

export interface SearchResult {
  player: Player;
  organizationName: string | null;
  ageLabel: string;
  heightCm: number | null;
  matchScore: number;
  highlights: string[];
  trend: number[];
  /** True when the viewer may not see this player, so the card renders locked. */
  withheld: boolean;
  withheldReason?: string | null;
}

export interface ParsedQuery {
  chips: { label: string; understood: boolean }[];
}

export interface ComparisonMetric {
  label: string;
  unit: string;
  higherIsBetter: boolean;
  values: (number | null)[];
  /** Set when error bars overlap, so the interface reports rather than ranks. */
  indistinguishable?: boolean;
  note?: string;
}

export interface Comparison {
  players: { player: Player; ageLabel: string; maturityOffsetYears: number | null }[];
  basis: "age" | "maturity";
  caveat: string | null;
  metrics: ComparisonMetric[];
  growth: { playerId: string; points: { date: string; value: number }[] }[];
}

export interface CoverageRow {
  organization: Organization;
  playerCount: number;
  lastSubmissionDays: number;
  medianStalenessDays: number;
  consentCompletePct: number;
  openFlags: number;
}

export interface OversightSummary {
  sport: Sport;
  playersTracked: number;
  academiesReporting: number;
  stalePct: number;
  openFlags: number;
  byRegion: { region: string; players: number; populationM: number }[];
  byAgeTier: { age: number; pro: number; youth: number; diaspora: number }[];
  academies: CoverageRow[];
  diaspora: { total: number; uncappedUnder21: number; newThisMonth: number };
}

export interface IntegrityFlag {
  id: string;
  type: "fraud" | "duplicate" | "anomaly";
  status: "open" | "confirmed" | "dismissed" | "needs_info";
  playerName: string;
  organizationName: string | null;
  raisedAt: string;
  ageDays: number;
  confidence: number;
  reason: string;
  evidence: string[];
  /** Populated for duplicate flags only. */
  records?: {
    label: string;
    playerId: string;
    createdAt: string;
    measurementCount: number;
    source: string;
    fields: { field: string; a: string; b: string; differs: boolean }[];
  } | null;
  history: { at: string; who: string; what: string }[];
}
