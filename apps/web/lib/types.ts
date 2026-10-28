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
  /** The competition or tournament, when known. */
  event?: string | null;
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
  /** All height readings, not only the six above. */
  heightReadings: number;
  /**
   * How many more height readings the late-bloomer check needs before it can run on this
   * player; 0 when none. The API applies the detector's own rule (age range, minimum readings,
   * analytics consent), so the screen never restates it.
   */
  heightReadingsNeeded: number;
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
  /** The date the forecast was made from (today), not the last measurement. */
  forecastFrom?: string | null;
  /** Which model and how its band was checked, or why there is no forecast. */
  forecastNote?: string | null;
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

/** One column of a performance table, as the sport module names it. */
export interface MetricColumn {
  key: string;
  label: string;
  unit: string | null;
}

/** A summary statistic the sport module defines, pooled over the player's valid records. */
export interface SummaryStat {
  key: string;
  label: string;
  value: number;
  /** "percent" means `value` is a 0 to 1 share. */
  format: "percent" | "number";
  basis: number;
}

/** A share of points against an average registered opponent, with its range (0 to 1). */
export interface PointShare {
  pointShare: number;
  low: number;
  high: number;
}

/**
 * Who a one-on-one match was against, as far as the viewer may know. The API sends a name and
 * id only when the viewer could open that player's own profile.
 */
export interface Opponent {
  /** False for an opponent who is not on the platform; nothing else about them is stored. */
  registered: boolean;
  id: string | null;
  name: string | null;
  /** How strong they were going into that month. Null when not yet reliably known. */
  strength: PointShare | null;
  /** Whether the match counted toward ratings (confirmed by a trusted source or both players). */
  counted: boolean;
}

export interface PerformanceRecord extends Omit<PerformanceEntry, "metrics"> {
  metrics: Record<string, number | string | boolean>;
  /** Why the record fails its sport module. Null when valid, or when the viewer may not see it. */
  problems: string[] | null;
  /** One-on-one sports only. */
  opponent?: Opponent | null;
}

/**
 * The table tennis rating (apps/api/app/services/rating.py, graded in ml/README.md). When
 * `shown` is false there is no number, and `note` says why.
 */
export interface Rating {
  shown: boolean;
  pointShare: number | null;
  low: number | null;
  high: number | null;
  /** Chance of winning a best-of-five match against an average registered opponent. */
  matchWin: number | null;
  ratedMatches: number;
  population: string;
  note: string | null;
}

/**
 * One kind of performance record, laid out by its sport module
 * (packages/shared/sports/<sport>.json). This screen knows nothing about any sport; it renders
 * the columns and statistics it is given.
 */
export interface PerformanceSection {
  schemaRef: string;
  sport: string;
  periodType: string;
  label: string;
  /** False when no sport module defines this kind of record. */
  known: boolean;
  columns: MetricColumn[];
  summary: SummaryStat[];
  excludedFromSummary: number;
  entries: PerformanceRecord[];
}

/** A sport the platform has a module for. Drives the add-player screen. */
export interface SportModule {
  sport: string;
  label: string;
  roleLabel: string;
  roles: string[];
  usesTier: boolean;
  /** Which genders the sport registers. Football: male only. Table tennis: both, kept apart. */
  genders: ("male" | "female")[];
  /** What a coach can tag from match video. Empty for a sport with none yet. */
  events: EventType[];
  /** Rates read from the tags (GET /analysis/{sport}/{key}). */
  analyses?: { key: string; label: string; rateLabel: string; minAttempts: number }[];
}

export interface EventType {
  key: string;
  label: string;
  /** The keyboard key the tagging screen binds to this type. */
  shortcut: string;
  outcomes: { key: string; label: string }[];
  /** What a coach can add after the outcome (decision 0007). */
  details?: EventDetail[];
}

export interface EventDetail {
  key: string;
  label: string;
  values: { key: string; label: string }[];
  /** The outcomes it applies to; empty means all. */
  outcomes: string[];
  /** [rows, cols] when the values are a grid (a goal mouth), row by row. */
  grid: [number, number] | null;
}

/** GET /analysis/{sport}/{key}: a success rate from tagged events (decision 0007). */
export interface EventAnalysis {
  sport: string;
  key: string;
  label: string;
  rateLabel: string;
  minAttempts: number;
  minForARate: number;
  gender: string;
  group: string | null;
  ageFrom: number | null;
  ageTo: number | null;
  genders: string[];
  groups: string[];
  population: string;
  attempts: number;
  successes: number;
  /** Null below minForARate attempts. */
  rate: number | null;
  breakdown: {
    key: string;
    label: string;
    grid: [number, number] | null;
    recorded: number;
    among: string | null;
    values: { key: string; label: string; attempts: number; successes: number; rate: number | null }[];
  }[];
  leaders: {
    playerId: string;
    fullName: string;
    position: string | null;
    ageLabel: string;
    attempts: number;
    successes: number;
    rate: number;
  }[];
  qualifying: number;
  player: {
    playerId: string;
    fullName: string;
    attempts: number;
    successes: number;
    rate: number | null;
    percentile: number | null;
  } | null;
  generated: number;
  note: string;
}

/**
 * The written summary, from GET /players/{id}/summary. `summary` is null when there is none,
 * and `note` always says why, or which model wrote it and that its numbers were checked.
 */
/** GET /players/{id}/similar. `items` may be empty; `note` always says what this is or why. */
export interface SimilarPlayers {
  items: {
    playerId: string;
    fullName: string;
    position: string | null;
    ageLabel: string;
    /** In standard deviations on a typical statistic. */
    distance: number;
    /** The statistics on which the two are most alike, in words. */
    alike: string[];
  }[];
  note: string;
}

export interface ProfileSummary {
  summary: string | null;
  note: string;
  model: string | null;
  /** Still being written: ask again shortly. */
  pending?: boolean;
}

export interface PlayerProfile {
  player: Player;
  organizationName: string | null;
  ageLabel: string;
  latest: { heightCm: number | null; weightKg: number | null };
  growth: GrowthSeries;
  maturity: MaturityEstimate | null;
  percentiles: Percentile[];
  /** Why there are no percentiles when they are withheld on purpose (analytics consent). */
  percentilesNote?: string | null;
  /** Null for sports without a rating. */
  rating?: Rating | null;
  performance: PerformanceSection[];
  flags: FlagSummary[];
  flagReason: string | null;
  /** Records merged into this one (second registrations of the same player). */
  mergedRecords?: MergedRecord[];
  provenance: {
    measurementCount: number;
    performanceCount: number;
    consents: { purpose: string; granted: boolean }[];
  };
  /** What the current role is permitted to do, decided by the API, not by the frontend. */
  permissions: { canEdit: boolean; canLog: boolean; canSeeFlags: boolean };
}

export interface MergedRecord {
  id: string;
  fullName: string;
  /** Null for a merge made before merges were recorded (some generated data). */
  mergedOn: string | null;
  mergedBy: string | null;
  /** Decided by the API: the caller may undo it, and it was recorded so it can be. */
  undoable: boolean;
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
  /** All 27 governorates, empty ones included, by players per million. */
  byRegion: { code: string; region: string; regionAr: string; players: number; populationM: number }[];
  /** Players at an Egyptian club with no governorate set. */
  playersWithoutGovernorate: number;
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
  /** The rule that raised it, e.g. "fraud.age_misrepresentation". */
  detector: string | null;
  /** Null when the rule has no calibrated probability, which is every detector today. */
  confidence: number | null;
  reason: string;
  evidence: string[];
  /** Populated for duplicate flags only. */
  records?: {
    label: string;
    playerId: string;
    otherPlayerId: string;
    createdAt: string;
    measurementCount: number;
    source: string;
    fields: { field: string; a: string; b: string; differs: boolean }[];
  } | null;
  history: { at: string; who: string; what: string }[];
}

/** POST /players/import/preview and /players/import. See apps/api/app/services/imports.py. */
export interface PlayerImport {
  fileProblems: string[];
  rows: {
    /** Line in the file, counting the header as 1. */
    line: number;
    name: string;
    /** Preview: ready, confirm or rejected. After an import: created, skipped or rejected. */
    status: "ready" | "confirm" | "rejected" | "created" | "skipped";
    problems: string[];
    warnings: string[];
    playerId: string | null;
  }[];
  counts: Record<string, number>;
  saved: boolean;
}

/** GET /players/{id}/radar. See apps/api/app/services/radar.py. */
/** Non-penalty goals against non-penalty xG; GET /players/{id}/pro-seasons. */
export interface Finishing {
  npGoals: number;
  npxg: number;
  /** 10th to 90th percentile of goals an ordinary finisher scores from these chances. */
  low: number | null;
  high: number | null;
  verdict: "above" | "below" | "in line" | "too few chances";
  seasons: number;
}

export interface ProSeasons {
  /** Newest first. */
  seasons: {
    season: string;
    competition: string;
    club: string | null;
    minutes: number;
    finishing: Finishing;
    /** Null for the first season the league data covers. */
    breakout: { flagged: boolean; score: number | null; reason: string; considered: boolean } | null;
  }[];
  career: Finishing | null;
  trends: {
    season: string;
    previous: string;
    minutesBefore: number;
    minutesAfter: number;
    changes: { key: string; label: string; before: number; after: number; unit: string }[];
  }[];
  note: string | null;
}

export interface PlayerRadar {
  axes: {
    key: string;
    label: string;
    value: number;
    unit: string;
    /** 1 to 99, higher is better; null when there are too few comparable players. */
    percentile: number | null;
    comparedWith: number;
  }[];
  /** Who the percentiles are among, in words; null when there is no radar. */
  population: string | null;
  note: string;
}

/** GET /explore/scatter. See apps/api/app/services/explore.py. Echoes the filters it used. */
export interface Scatter {
  sport: string;
  gender: "male" | "female";
  /** Football position group; null for every position, and always null in table tennis. */
  group: string | null;
  ageFrom: number | null;
  ageTo: number | null;
  x: string;
  y: string;
  stats: { key: string; label: string; unit: string; higherIsBetter: boolean }[];
  genders: ("male" | "female")[];
  groups: string[];
  /** Only players the viewer may open; `total` counts the whole group. */
  points: {
    playerId: string;
    fullName: string;
    position: string | null;
    ageLabel: string;
    x: number;
    y: number;
  }[];
  /** Null when the group is too small for median lines to mean anything. */
  medians: { x: number; y: number } | null;
  total: number;
  population: string;
  focus: string | null;
  note: string;
}

export interface ScatterQuery {
  sport?: string;
  gender?: string;
  group?: string;
  ageFrom?: number;
  ageTo?: number;
  x?: string;
  y?: string;
  focus?: string;
  /** With a focus and no ages: use the focus player's own age band (the API's default). */
  ownAge?: boolean;
}

/** One leader on a board. `percentile` is among the whole group, higher is better. */
export interface Leader {
  playerId: string;
  fullName: string;
  position: string | null;
  ageLabel: string;
  value: number;
  percentile: number;
  /** Only on a board's `focus`: their place among the players the viewer may open. */
  rank: number | null;
}

/** GET /explore/leaders. See apps/api/app/services/explore.py. Echoes the filters it used. */
export interface Leaders {
  sport: string;
  gender: "male" | "female";
  group: string | null;
  ageFrom: number | null;
  ageTo: number | null;
  stats: Scatter["stats"];
  genders: ("male" | "female")[];
  groups: string[];
  boards: {
    key: string;
    label: string;
    unit: string;
    higherIsBetter: boolean;
    comparedWith: number;
    /** Null when too few players have it or all are equal; `leaders` is then empty. */
    median: number | null;
    leaders: Leader[];
    focus: Leader | null;
  }[];
  total: number;
  shown: number;
  population: string;
  focus: string | null;
  note: string;
}

/** POST /assistant. See apps/api/app/services/assistant.py. No number in it is the model's. */
export interface AssistantAnswer {
  question: string;
  reading: {
    intent: "leaders" | "player" | "similar" | "compare" | "unsupported";
    sport: string | null;
    gender: string | null;
    positionGroup: string | null;
    ageFrom: number | null;
    ageTo: number | null;
    statistic: string | null;
    players: string[];
  };
  /** The reading in words, for "How this was read". */
  chips: string[];
  answer: string;
  columns: string[];
  /** `playerId` is set when the first cell is a player the viewer may open. */
  rows: { playerId: string | null; cells: string[] }[];
  /** The screen that shows the same thing, where the filters can be set by hand. */
  link: { label: string; href: string } | null;
  note: string;
  model: string;
}

/** One event tagged from match video. See apps/api/app/services/events.py. */
export interface MatchEvent {
  id: string;
  playerId: string;
  /** Only on a match's list, where several players' tags are shown together. */
  playerName: string | null;
  matchDate: string;
  matchLabel: string | null;
  eventType: string;
  outcome: string;
  /** 0 to 100: own goal line to the opponent's, as the team attacks. Null when not placed. */
  x: number | null;
  /** 0 to 100: left touchline to right. */
  y: number | null;
  videoSeconds: number | null;
  /** {detail: value}, as the sport module defines them. */
  details?: Record<string, string>;
}

/** GET /events: one match's tags for the coach's club. */
export interface MatchTags {
  matchDate: string;
  matchLabel: string | null;
  events: MatchEvent[];
  /** Totals the tags add up to, beside what was logged for that date (null: nothing logged). */
  players: {
    playerId: string;
    playerName: string;
    tagged: Record<string, number>;
    logged: Record<string, number | null> | null;
  }[];
}

/** GET /players/{id}/events. */
export interface PlayerEvents {
  events: MatchEvent[];
  matches: number;
  /** "<type>.<outcome>" to how many. */
  counts: Record<string, number>;
  note: string;
}

/** POST /results/import/preview and /results/import. See apps/api/app/services/results_import.py. */
export interface ResultsImport {
  fileProblems: string[];
  rows: {
    line: number;
    /** "Player A v Player B", as written in the file. */
    name: string;
    event: string;
    /** Preview: ready, duplicate or rejected. After an import, imported instead of ready. */
    status: "ready" | "imported" | "duplicate" | "rejected";
    problems: string[];
    warnings: string[];
    /** Worked out from the game scores, e.g. "3-1 (42-31 points), best of 5, for <name>". */
    score: string | null;
  }[];
  counts: Record<string, number>;
  saved: boolean;
  recordsWritten: number;
}
