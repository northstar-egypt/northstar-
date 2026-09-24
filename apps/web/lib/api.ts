/**
 * The one place the web app talks to the outside world.
 *
 * Every read this app needs is now a real endpoint. The fixtures are gone from this file and
 * `lib/fixtures.ts` is no longer imported by anything that ships a screen.
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
 * There is no authentication yet; the security track owns that decision. The API resolves a
 * caller from an `X-NorthStar-User` header and honours it only when it is running in
 * development. `lib/auth.tsx` puts the chosen account in localStorage and this module attaches
 * it. When real sessions land, `authHeaders` is the only function here that changes.
 */

import type {
  Comparison,
  IntegrityFlag,
  OversightSummary,
  ParsedQuery,
  PlayerProfile,
  SearchResult,
  SessionUser,
  SquadRow,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Kept so any remaining reference reads false rather than breaking the build. */
export const USING_FIXTURES = false;

/** Where `lib/auth.tsx` stores the account the role switcher is acting as. */
export const IDENTITY_KEY = "northstar.devIdentity";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** True when the caller is not signed in, or the API refuses the stand-in identity. */
  get isAuth(): boolean {
    return this.status === 401;
  }

  /** True when the caller is signed in but not allowed to do this. */
  get isForbidden(): boolean {
    return this.status === 403;
  }
}

export class NotImplementedError extends Error {
  constructor(readonly endpoint: string, message: string) {
    super(message);
    this.name = "NotImplementedError";
  }
}

function authHeaders(): Record<string, string> {
  try {
    const identity = window.localStorage.getItem(IDENTITY_KEY);
    return identity ? { "X-NorthStar-User": identity } : {};
  } catch {
    // localStorage throws in private browsing. An unauthenticated request that gets a clean
    // 401 is a better outcome than a crash inside a render.
    return {};
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
        ...(init.headers ?? {}),
      },
    });
  } catch {
    // A network failure is not a 500. Saying the API is unreachable points at the right
    // problem, which is usually that nobody started it.
    throw new ApiError(0, `Cannot reach the API at ${API_URL}. Is it running?`);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // A non-JSON error body is not worth a second failure.
    }
    throw new ApiError(response.status, detail);
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

/** Who the API believes is calling. Useful for confirming the header actually worked. */
export async function getSession(): Promise<SessionUser> {
  return request<SessionUser>("/me");
}

export interface DevIdentity {
  id: string;
  email: string;
  fullName: string;
  role: string;
  organizationId: string | null;
  organizationName: string | null;
  linkedPlayerId: string | null;
}

/**
 * Accounts the development role switcher can act as.
 *
 * Development only. The API returns 404 for this outside development, which is what will
 * happen the moment real authentication exists, and `lib/auth.tsx` treats that as "the role
 * switcher is over" rather than as an error.
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
export async function getProfile(playerId: string): Promise<PlayerProfile | null> {
  try {
    return await request<PlayerProfile>(`/players/${encodeURIComponent(playerId)}/profile`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/* ------------------------------------------------------------------ writes, not built */

/**
 * TODO(api): POST /players
 *
 * Not built. The read API landed first; this needs a Player row and the PlayerOrganization
 * row linking them to the caller's organization, created in one transaction, because a player
 * with no affiliation is invisible to every screen in this app.
 *
 * It throws rather than resolving with a fake id. The add-player screen catches it and says
 * so. Pretending a save succeeded and then routing to a dashboard the player is not on is a
 * worse failure than an honest error, especially on the one screen a coach uses in the field.
 */
export async function createPlayer(input: Record<string, unknown>): Promise<{ id: string }> {
  throw new NotImplementedError(
    "POST /players",
    "Saving a new player is not built yet. The API serves reads only.",
  );
}

/**
 * TODO(api): POST /players/{id}/measurements
 *
 * Not built. One Measurement row per metric, long format, source coach_logged, recorded_by the
 * caller. The API should validate plausibility and return a warning rather than rejecting: a
 * coach who genuinely measured an implausible value must be able to record it, because that is
 * the observation the detectors need.
 */
export async function logMeasurement(
  playerId: string,
  input: Record<string, unknown>,
): Promise<{ ok: true }> {
  throw new NotImplementedError(
    "POST /players/{id}/measurements",
    "Logging a measurement is not built yet. The API serves reads only.",
  );
}

/* ------------------------------------------------------------------ search */

export interface SearchFilters {
  // Nullable as well as optional: the screens hold these in state that starts empty, and a
  // cleared dropdown is null rather than undefined.
  tier?: string | null;
  position?: string | null;
  sport?: string | null;
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
): Promise<IntegrityFlag> {
  return request<IntegrityFlag>(
    `/integrity/flags/${encodeURIComponent(flagId)}/decision`,
    { method: "POST", body: JSON.stringify({ decision, reason }) },
  );
}
