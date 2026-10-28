/**
 * The one place the web app talks to the outside world.
 *
 * Every read and write this app needs is now a real endpoint. The fixtures are gone from this
 * file and `lib/fixtures.ts` is no longer imported by anything that ships a screen.
 *
 * The point of routing everything through this module has not changed: a screen imports from
 * here and never from `fetch` directly, so the next change of transport is contained again.
 *
 * Two rules that survived the switch, and are now the API's job rather than a comment:
 *   1. Scoping and consent filtering happen server side. If a field must not be seen by the
 *      current role, the API does not send it. Nothing here hides anything.
 *   2. Aggregates are computed server side. This app never fetches rows in order to count
 *      them.
 *
 * Identity
 * --------
 * The session is an HttpOnly cookie set by `POST /auth/login`. This code never sees the token,
 * which is the point: a script injected into the page cannot read it either. Every request
 * below is sent with `credentials: "include"` so the browser attaches the cookie, and the API
 * decides who is calling. `lib/auth.tsx` only asks `/me` who that is.
 */

import type {
  AssistantAnswer,
  EventAnalysis,
  ResultsImport,
  MatchEvent,
  MatchTags,
  PlayerEvents,
  Leaders,
  Scatter,
  ScatterQuery,
  Comparison,
  IntegrityFlag,
  OversightSummary,
  ParsedQuery,
  PlayerProfile,
  ProfileSummary,
  SearchResult,
  SessionUser,
  SimilarPlayers,
  SportModule,
  SquadRow,
  PlayerImport,
  PlayerRadar,
  ProSeasons,
  ScoutHome,
  ClubGaps,
  GapOptions,
  NationalGaps,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Kept so any remaining reference reads false rather than breaking the build. */
export const USING_FIXTURES = false;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    /** The parsed `detail` when the API sent a structured one, for 409 and 422 on writes. */
    readonly detail: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** True when the caller is not signed in, or the session has expired. */
  get isAuth(): boolean {
    return this.status === 401;
  }

  /** True when the caller is signed in but not allowed to do this. */
  get isForbidden(): boolean {
    return this.status === 403;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      cache: "no-store",
      // Sends the session cookie. The API only accepts it from the web app's own origin.
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(init.headers ?? {}),
      },
    });
  } catch {
    // A network failure is not a 500. Saying the API is unreachable points at the right
    // problem, which is usually that nobody started it.
    throw new ApiError(0, `Cannot reach the API at ${API_URL}. Is it running?`);
  }

  if (!response.ok) {
    let message = response.statusText;
    let detail: unknown = null;
    try {
      const body = await response.json();
      detail = body?.detail ?? null;
      if (typeof detail === "string") message = detail;
      else if (typeof (detail as { message?: unknown })?.message === "string") {
        message = (detail as { message: string }).message;
      }
    } catch {
      // A non-JSON error body is not worth a second failure.
    }
    throw new ApiError(response.status, message, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/* ------------------------------------------------------------------ health */

export interface Health {
  ok: boolean;
  detail: string;
}

export async function getHealth(): Promise<Health> {
  try {
    const res = await fetch(`${API_URL}/health/db`, { cache: "no-store" });
    const data = await res.json();
    return { ok: data.status === "ok", detail: data.database ?? "" };
  } catch {
    return { ok: false, detail: "API unreachable" };
  }
}

/* ------------------------------------------------------------------ identity */

/** Who the current session belongs to. Rejects with a 401 `ApiError` when signed out. */
export async function getSession(): Promise<SessionUser> {
  return request<SessionUser>("/me");
}

/**
 * Sign in. On success the API sets the session cookie and returns who signed in. A wrong
 * email and a wrong password produce the same 401 and the same message, on purpose.
 */
export async function login(email: string, password: string): Promise<SessionUser> {
  return request<SessionUser>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

/** Sign out. Clears the session cookie. Safe to call when already signed out. */
export async function logout(): Promise<void> {
  return request<void>("/auth/logout", { method: "POST" });
}

export interface DevIdentity {
  id: string;
  email: string;
  fullName: string;
  role: string;
  organizationId: string | null;
  organizationName: string | null;
  linkedPlayerId: string | null;
  /** The published password of every synthetic account. */
  demoPassword: string;
}

/**
 * Synthetic demo accounts, one per role, for the login screen's demo buttons.
 *
 * Development only: the API returns 404 elsewhere, and `lib/auth.tsx` then simply shows no
 * demo buttons. The buttons sign in through the real `login` above; this saves typing.
 */
export async function getDevIdentities(): Promise<DevIdentity[]> {
  return request<DevIdentity[]>("/dev/identities");
}

/* ------------------------------------------------------------------ squad */

export async function getSquad(organizationId?: string): Promise<SquadRow[]> {
  const query = organizationId ? `?organization_id=${encodeURIComponent(organizationId)}` : "";
  return request<SquadRow[]>(`/players${query}`);
}

/* ------------------------------------------------------------------ profile */

/**
 * Returns null when the player does not exist *or* the caller may not see them.
 *
 * Those are deliberately the same answer. The API returns 404 for both, because a
 * distinguishable response would tell an unauthorised caller that the player exists, and for
 * a child without scouting consent that is the disclosure the rule exists to prevent. This
 * function must not try to be more helpful than that.
 */
export async function getProfile(
  playerId: string,
): Promise<PlayerProfile | { mergedInto: string } | null> {
  try {
    return await request<PlayerProfile>(`/players/${encodeURIComponent(playerId)}/profile`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      // A record merged into another says which, when the caller may open that one.
      const into = (error.detail as { mergedInto?: unknown } | null)?.mergedInto;
      return typeof into === "string" ? { mergedInto: into } : null;
    }
    throw error;
  }
}

/** The profile's written summary. Null on 404, for the same reason as `getProfile`. */
export async function getSummary(playerId: string): Promise<ProfileSummary | null> {
  try {
    return await request<ProfileSummary>(`/players/${encodeURIComponent(playerId)}/summary`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** Percentiles of a player's match statistics among comparable players. Null on 404. */
export async function getScoutHome(): Promise<ScoutHome> {
  return request<ScoutHome>("/home/scout");
}

/** The ids on the caller's shortlist; null when the caller has no shortlist (not a scout). */
export async function getShortlistIds(): Promise<string[] | null> {
  try {
    return (await request<{ playerIds: string[] }>("/shortlist")).playerIds;
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) return null;
    throw error;
  }
}

export async function saveToShortlist(playerId: string, note = ""): Promise<void> {
  await request<void>(`/shortlist/${encodeURIComponent(playerId)}`, {
    method: "PUT",
    body: JSON.stringify({ note }),
  });
}

export async function removeFromShortlist(playerId: string): Promise<void> {
  await request<void>(`/shortlist/${encodeURIComponent(playerId)}`, { method: "DELETE" });
}

export async function getGapOptions(): Promise<GapOptions> {
  return request<GapOptions>("/gaps");
}

export async function getClubGaps(clubId: string, season?: string | null): Promise<ClubGaps> {
  const query = season ? `?season=${encodeURIComponent(season)}` : "";
  return request<ClubGaps>(`/gaps/club/${encodeURIComponent(clubId)}${query}`);
}

/** Needs as group:attribute,attribute, e.g. "full_backs:crosses_per_90,tackles_per_90". */
export async function getNationalGaps(needs: string[]): Promise<NationalGaps> {
  const query = needs.map((n) => `need=${encodeURIComponent(n)}`).join("&");
  return request<NationalGaps>(`/gaps/national?${query}`);
}

export async function getProSeasons(playerId: string): Promise<ProSeasons | null> {
  try {
    return await request<ProSeasons>(`/players/${encodeURIComponent(playerId)}/pro-seasons`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function getRadar(playerId: string): Promise<PlayerRadar | null> {
  try {
    return await request<PlayerRadar>(`/players/${encodeURIComponent(playerId)}/radar`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** Players whose match record looks most like this one's. Null on 404, as `getProfile`. */
export async function getSimilar(playerId: string): Promise<SimilarPlayers | null> {
  try {
    return await request<SimilarPlayers>(`/players/${encodeURIComponent(playerId)}/similar`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/* ------------------------------------------------------------------ sports */

/** Every sport with a module in packages/shared/sports, with its roles. */
export async function getSports(): Promise<SportModule[]> {
  return request<SportModule[]>("/sports");
}

/* ------------------------------------------------------------------ writes */

export interface MeasurementInput {
  metric: string;
  value: number;
  unit: string;
  confidence?: "measured" | "estimated";
}

/** One visit: everything measured about one player on one day. */
export interface MeasurementBatch {
  measuredAt: string;
  metrics: MeasurementInput[];
  /** Set only after a person has seen the warnings and confirmed the readings are right. */
  acknowledgeWarnings?: boolean;
}

export interface NewPlayer {
  fullName: string;
  dateOfBirth: string;
  sex?: string | null;
  /** ISO 3166-1 alpha-2, for example EG. */
  nationality: string[];
  isEgyptEligible: boolean;
  primarySport: string;
  tier?: string | null;
  position?: string | null;
  /** The sign-up consent form. For a minor it is signed by a guardian, who must be named. */
  consent: { signed: boolean; guardianName?: string | null };
  measurements?: MeasurementBatch;
}

export interface MeasurementWarning {
  metric: string;
  value: number;
  message: string;
}

export interface PlayerCreated {
  player: { id: string; isMinor: boolean };
  organizationId: string;
  acknowledgedWarnings: MeasurementWarning[];
  /** "player", or "guardian:<name>" for a minor. */
  consentGrantedBy: string;
}

/**
 * Why a write did not happen, in a shape the screen can act on.
 *
 * `confirm` means the API found readings that look wrong but could be real. Nothing was saved;
 * show the warnings and let the person resend with `acknowledgeWarnings`. `fix` means the
 * input cannot be stored as it is. Anything else is rethrown untouched.
 */
export type WriteRefusal =
  | { kind: "confirm"; message: string; warnings: MeasurementWarning[] }
  | { kind: "fix"; message: string; problems: string[] };

export function writeRefusal(error: unknown): WriteRefusal | null {
  if (!(error instanceof ApiError)) return null;
  const detail = (error.detail ?? {}) as { warnings?: MeasurementWarning[]; problems?: unknown };
  if (error.status === 409 && Array.isArray(detail.warnings)) {
    return { kind: "confirm", message: error.message, warnings: detail.warnings };
  }
  if (error.status === 422) {
    // Our own checks send `problems`. FastAPI's schema validation sends a list of
    // {loc, msg}, which is flattened here so the screen has one thing to render.
    const problems = Array.isArray(detail.problems)
      ? (detail.problems as string[])
      : Array.isArray(error.detail)
        ? (error.detail as { loc?: unknown[]; msg?: string }[]).map(
            (d) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? "invalid"}`,
          )
        : [];
    return { kind: "fix", message: error.message, problems };
  }
  return null;
}

/**
 * POST /players. Creates the player, their affiliation to the caller's organization, and the
 * first visit, in one transaction. Either all of it is saved or none of it is, so a failure
 * here never leaves behind a player the screen said was not saved.
 */
export async function createPlayer(input: NewPlayer): Promise<PlayerCreated> {
  return request<PlayerCreated>("/players", { method: "POST", body: JSON.stringify(input) });
}

/** What importing this CSV would do, row by row. Saves nothing. */
export async function previewImport(csv: string): Promise<PlayerImport> {
  return request<PlayerImport>("/players/import/preview", {
    method: "POST",
    body: JSON.stringify({ csv }),
  });
}

/** Import the ready rows and the confirmed ones. The server checks the file again first. */
export async function importPlayers(csv: string, confirm: number[]): Promise<PlayerImport> {
  return request<PlayerImport>("/players/import", {
    method: "POST",
    body: JSON.stringify({ csv, confirm }),
  });
}

/** What importing these table tennis results would do, match by match. Saves nothing. */
export async function previewResults(csv: string): Promise<ResultsImport> {
  return request<ResultsImport>("/results/import/preview", { method: "POST", body: JSON.stringify({ csv }) });
}

/** Import the ready matches. The server checks the file again first. */
export async function importResults(csv: string): Promise<ResultsImport> {
  return request<ResultsImport>("/results/import", { method: "POST", body: JSON.stringify({ csv }) });
}

/** POST /players/{id}/measurements. One visit for a player the caller may log for. */
export async function logMeasurement(
  playerId: string,
  input: MeasurementBatch,
): Promise<{ acknowledgedWarnings: MeasurementWarning[] }> {
  return request(`/players/${encodeURIComponent(playerId)}/measurements`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

/**
 * POST /players/{id}/consent/withdraw. Records a guardian's (or an adult player's) withdrawal
 * of analytics or scouting visibility. It takes effect at once everywhere consent is checked.
 */
export async function withdrawConsent(
  playerId: string,
  input: { purposes: string[]; guardianName?: string },
): Promise<{
  withdrawn: string[];
  alreadyWithdrawn: string[];
  withdrawnBy: string;
  consents: Record<string, boolean>;
}> {
  return request(`/players/${encodeURIComponent(playerId)}/consent/withdraw`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

/* ------------------------------------------------------------------ search */

export interface SearchFilters {
  // Nullable as well as optional: the screens hold these in state that starts empty, and a
  // cleared dropdown is null rather than undefined.
  tier?: string | null;
  position?: string | null;
  sport?: string | null;
  /** Only offered for a sport that registers both genders, which are searched separately. */
  sex?: "male" | "female" | null;
  egyptOnly?: boolean;
  minAge?: number | null;
  maxAge?: number | null;
  minHeightCm?: number | null;
  limit?: number;
  offset?: number;
}

/**
 * Structured filters plus whatever can be read out of the query text.
 *
 * The natural language half needs an embedding model nobody has chosen yet. What comes back
 * in `parsed.chips` is the API's account of how it read the sentence, and a chip marked
 * `understood: false` genuinely changed nothing about the results. The screen renders that
 * under "How this was read".
 */
export async function search(
  query: string,
  filters: SearchFilters = {},
): Promise<{ parsed: ParsedQuery; results: SearchResult[]; total: number }> {
  return request<{ parsed: ParsedQuery; results: SearchResult[]; total: number }>("/search", {
    method: "POST",
    body: JSON.stringify({
      query,
      tier: filters.tier || null,
      position: filters.position || null,
      sport: filters.sport || null,
      sex: filters.sex || null,
      minAge: filters.minAge ?? null,
      maxAge: filters.maxAge ?? null,
      minHeightCm: filters.minHeightCm ?? null,
      egyptEligibleOnly: Boolean(filters.egyptOnly),
      limit: filters.limit ?? 50,
      offset: filters.offset ?? 0,
    }),
  });
}

/* ------------------------------------------------------------------ comparison */

export async function getComparison(
  playerIds: string[],
  basis: "age" | "maturity",
): Promise<Comparison> {
  const players = playerIds.map(encodeURIComponent).join(",");
  return request<Comparison>(`/compare?players=${players}&basis=${basis}`);
}

/* ------------------------------------------------------------------ explorer */

/** Comparable players on two statistics. Unset filters are left to the API's defaults. */
export async function getScatter(query: ScatterQuery): Promise<Scatter> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  return request<Scatter>(`/explore/scatter?${params.toString()}`);
}

/** For each statistic, a group's median and its best players the viewer may open. */
export async function getLeaders(query: Omit<ScatterQuery, "x" | "y">): Promise<Leaders> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  return request<Leaders>(`/explore/leaders?${params.toString()}`);
}

/* ------------------------------------------------------------------ assistant */

/** A question in plain words. A 503 means the local model is not running; its message says so. */
export async function askAssistant(question: string): Promise<AssistantAnswer> {
  return request<AssistantAnswer>("/assistant", {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

/* ------------------------------------------------------------------ match events */

export interface EventInput {
  playerId: string;
  matchDate: string;
  matchLabel: string | null;
  eventType: string;
  outcome: string;
  x: number | null;
  y: number | null;
  videoSeconds: number | null;
}

/** Save one event tagged from video. A 422 carries every reason in its message. */
export async function tagEvent(input: EventInput): Promise<MatchEvent> {
  return request<MatchEvent>("/events", { method: "POST", body: JSON.stringify(input) });
}

/** Replace a tag's details (where in the goal, technique...): the coach adds them after the outcome. */
export async function setEventDetails(eventId: string, details: Record<string, string>): Promise<MatchEvent> {
  return request<MatchEvent>(`/events/${encodeURIComponent(eventId)}/details`, {
    method: "PUT",
    body: JSON.stringify({ details }),
  });
}

/** GET /analysis/{sport}/{key}: finishing, points by stroke. Null on a question it cannot answer. */
export async function getEventAnalysis(
  sport: string,
  key: string,
  query: { gender?: string | null; group?: string | null; ageFrom?: number | null; ageTo?: number | null; player?: string | null } = {},
): Promise<EventAnalysis> {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(name, String(value));
  }
  return request<EventAnalysis>(`/analysis/${encodeURIComponent(sport)}/${encodeURIComponent(key)}?${params.toString()}`);
}

export async function untagEvent(eventId: string): Promise<void> {
  await request<void>(`/events/${encodeURIComponent(eventId)}`, { method: "DELETE" });
}

export async function getMatchTags(matchDate: string, matchLabel: string): Promise<MatchTags> {
  const params = new URLSearchParams({ matchDate });
  if (matchLabel.trim()) params.set("matchLabel", matchLabel.trim());
  return request<MatchTags>(`/events?${params.toString()}`);
}

export async function getPlayerEvents(playerId: string, type?: string): Promise<PlayerEvents | null> {
  const query = type ? `?type=${encodeURIComponent(type)}` : "";
  try {
    return await request<PlayerEvents>(`/players/${encodeURIComponent(playerId)}/events${query}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/* ------------------------------------------------------------------ oversight */

export async function getOversight(sport = "football"): Promise<OversightSummary> {
  return request<OversightSummary>(`/oversight?sport=${encodeURIComponent(sport)}`);
}

/* ------------------------------------------------------------------ integrity */

/**
 * The review queue.
 *
 * Flags are read from the database, not computed per request. They get there by running
 * `python -m ml.write_flags`, which is the batch job connecting `ml/detectors` to this screen.
 * An empty board usually means that has not been run rather than that nothing is wrong.
 */
export async function getFlags(status = "open"): Promise<IntegrityFlag[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "?status=";
  return request<IntegrityFlag[]>(`/integrity/flags${query}`);
}

/**
 * Record a decision. The reason is required by the API, not only by this form.
 *
 * Each decision plus its reason is a labelled example, and labelled examples are what the
 * detectors' precision and recall are computed from.
 */
export async function decideFlag(
  flagId: string,
  decision: "confirmed" | "dismissed" | "needs_info",
  reason: string,
  /** Confirming a duplicate merges its records; this is the one to keep. */
  keepPlayerId?: string,
): Promise<IntegrityFlag> {
  return request<IntegrityFlag>(
    `/integrity/flags/${encodeURIComponent(flagId)}/decision`,
    { method: "POST", body: JSON.stringify({ decision, reason, keepPlayerId }) },
  );
}

/** Undo a merge: the merged record's history goes back to it and the case reopens. */
export async function undoMerge(mergedId: string, reason: string): Promise<void> {
  await request<void>(`/integrity/merges/${encodeURIComponent(mergedId)}/undo`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}
