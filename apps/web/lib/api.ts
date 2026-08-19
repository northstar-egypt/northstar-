/**
 * The one place the web app talks to the outside world.
 *
 * Today the API serves `/health` and `/health/db` and nothing else. Every other endpoint this
 * app needs is unbuilt, so each function below returns a synthetic fixture and carries a TODO
 * naming the endpoint it should call and the tables behind it. Those TODOs are the application
 * track's request to the data track, written where they cannot be lost.
 *
 * The point of routing everything through this module is that switching to the real API is a
 * change here and nowhere else. No screen imports fixtures directly.
 *
 * Two rules that must survive the switch:
 *   1. Scoping and consent filtering happen server side. If a field must not be seen by the
 *      current role, the API must not send it. Hiding it in the browser is not access control.
 *   2. Aggregates are computed server side. This app must never fetch rows in order to count
 *      them.
 */

import {
  FLAGS,
  OVERSIGHT,
  PARSED_QUERY,
  SEARCH_RESULTS,
  SQUAD,
  comparison as fixtureComparison,
  profile as fixtureProfile,
} from "./fixtures";
import type {
  Comparison,
  IntegrityFlag,
  OversightSummary,
  ParsedQuery,
  PlayerProfile,
  SearchResult,
  SquadRow,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * True while the endpoints below are stubs. Flip to false as they land, or delete this and the
 * fixture imports once they all have.
 */
export const USING_FIXTURES = true;

/** Simulates a round trip so loading states are real rather than theoretical. */
function settle<T>(value: T, ms = 220): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

/* ------------------------------------------------------------------ health, real */

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

/* ------------------------------------------------------------------ squad */

/**
 * TODO(api): GET /players?organization_id=<caller's org>&active=true
 * Player joined through PlayerOrganization where end_date is null, scoped to the caller's
 * organization by the API. Needs days since last Measurement and the last six height readings
 * as part of the row, because fetching them per player would make this screen slow.
 */
export async function getSquad(): Promise<SquadRow[]> {
  return settle(SQUAD);
}

/* ------------------------------------------------------------------ profile */

/**
 * TODO(api): GET /players/{id}/profile
 * Player, current PlayerOrganization, all Measurement rows, PerformanceEntry rows, plus the ML
 * layer's forecast, maturity estimate, percentiles, and flags. The response must already be
 * filtered for the caller's role and for consent, and must include a permissions object so the
 * frontend does not have to infer what to render.
 */
export async function getProfile(playerId: string): Promise<PlayerProfile | null> {
  return settle(fixtureProfile(playerId));
}

/**
 * TODO(api): POST /players
 * Creates a Player and the PlayerOrganization row linking them to the caller's organization,
 * in one transaction. A player with no affiliation is invisible to every screen in this app.
 */
export async function createPlayer(input: Record<string, unknown>): Promise<{ id: string }> {
  console.info("createPlayer would POST", input);
  return settle({ id: "p-new" }, 400);
}

/**
 * TODO(api): POST /players/{id}/measurements
 * One Measurement row per metric, long format, source coach_logged, recorded_by the caller.
 * The API validates plausibility and returns a warning rather than rejecting: a coach who
 * genuinely measured an implausible value must be able to record it, because that is the
 * observation the detectors need. See docs/wireframes/03-add-edit-player.html.
 */
export async function logMeasurement(
  playerId: string,
  input: Record<string, unknown>,
): Promise<{ ok: true }> {
  console.info("logMeasurement would POST", playerId, input);
  return settle({ ok: true } as const, 400);
}

/* ------------------------------------------------------------------ search */

/**
 * TODO(api): POST /search
 * Structured filters map to Player columns and to values the ML layer wrote back. The natural
 * language half needs sentence-transformer embeddings, which the ML track has deferred until
 * they pick a model, so the filter half should ship first.
 *
 * Withheld results must arrive already stripped of the fields the caller may not see.
 */
export async function search(
  query: string,
  filters: Record<string, unknown>,
): Promise<{ parsed: ParsedQuery; results: SearchResult[]; total: number }> {
  console.info("search would POST", { query, filters });
  return settle({
    parsed: query.trim() ? PARSED_QUERY : { chips: [] },
    results: SEARCH_RESULTS,
    total: SEARCH_RESULTS.length,
  });
}

/* ------------------------------------------------------------------ comparison */

/**
 * TODO(api): GET /compare?players=<id>,<id>&basis=age|maturity
 * Percentiles must be computed against the same stated population for every player, otherwise
 * the columns are not comparable. Metric direction (higher or lower is better) should come
 * from metric definitions in packages/shared, not be hard coded per screen.
 */
export async function getComparison(
  playerIds: string[],
  basis: "age" | "maturity",
): Promise<Comparison> {
  console.info("getComparison would GET", playerIds, basis);
  return settle(fixtureComparison(basis));
}

/* ------------------------------------------------------------------ oversight */

/**
 * TODO(api): GET /oversight?sport=football
 * Aggregates only. Coverage by governorate needs a region field on Organization, which the
 * schema does not have yet. Raised in docs/wireframes/README.md.
 */
export async function getOversight(): Promise<OversightSummary> {
  return settle(OVERSIGHT);
}

/* ------------------------------------------------------------------ integrity */

/**
 * TODO(api): GET /integrity/flags?status=open
 * BLOCKED. There is no flag table in docs/schema.md. Nothing holds a raised flag with a type,
 * confidence, evidence, status, reviewer, decision, and reason. The ML track writes those, this
 * app reads them, and the security track audits them, so it belongs in the shared core.
 * Proposed field list is in docs/wireframes/08-integrity-board.html.
 */
export async function getFlags(): Promise<IntegrityFlag[]> {
  return settle(FLAGS);
}

/**
 * TODO(api): POST /integrity/flags/{id}/decision
 * Records the outcome, the reviewer, and the reason, and appends to AuditLog. The reason is not
 * optional: each decision plus its reason is a labelled example, and labelled examples are what
 * the detectors' precision and recall are computed from.
 */
export async function decideFlag(
  flagId: string,
  decision: "confirmed" | "dismissed" | "needs_info",
  reason: string,
): Promise<{ ok: true }> {
  console.info("decideFlag would POST", { flagId, decision, reason });
  return settle({ ok: true } as const, 350);
}
