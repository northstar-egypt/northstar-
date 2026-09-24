"use client";

/**
 * Session state for the web app.
 *
 * IMPORTANT: this is still not authentication. There is no auth endpoint on the API. The
 * security workstream owns that decision and it has not been made, so this module picks a real
 * account from the database and remembers which one, rather than verifying anybody.
 *
 * What changed when the API landed: the accounts are real. They come from `/dev/identities`,
 * which the API serves only in development and which returns the value to put in the
 * `X-NorthStar-User` header. That header is how every request in `lib/api.ts` identifies
 * itself, which means the role switcher now changes what the server sends rather than what the
 * browser draws.
 *
 * What it deliberately still does NOT do, because doing it here would be security theatre:
 *   - verify a password
 *   - decide what data the user may see
 *
 * Access control belongs in the API, and now it is there: `apps/api/app/services/access.py`.
 * Every screen treats role as a hint for what to render, never as the enforcement boundary.
 *
 * When real auth lands, `signIn` calls a login endpoint that returns a token, the identity in
 * localStorage becomes that token, and `ROUTE_ROLES` below stays exactly as it is.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getDevIdentities, IDENTITY_KEY, type DevIdentity } from "./api";
import type { SessionUser, UserRole } from "./types";

const STORAGE_KEY = "northstar.devSession";

interface AuthState {
  user: SessionUser | null;
  ready: boolean;
  /** Accounts the API will accept. Empty when the API is unreachable or not in development. */
  identities: Record<string, DevIdentity>;
  /** Set when the identity list could not be loaded, so the login screen can say why. */
  error: string | null;
  signIn: (role: UserRole) => void;
  signOut: () => void;
  /** Development only. Goes away with the real auth implementation. */
  switchRole: (role: UserRole) => void;
}

const AuthContext = createContext<AuthState | null>(null);

function toSessionUser(identity: DevIdentity): SessionUser {
  return {
    id: identity.id,
    fullName: identity.fullName,
    email: identity.email,
    role: identity.role as UserRole,
    organizationId: identity.organizationId,
    organizationName: identity.organizationName,
    linkedPlayerId: identity.linkedPlayerId,
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [identities, setIdentities] = useState<Record<string, DevIdentity>>({});
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let alive = true;

    getDevIdentities()
      .then((rows) => {
        if (!alive) return;
        const byRole: Record<string, DevIdentity> = {};
        for (const row of rows) byRole[row.role] = row;
        setIdentities(byRole);

        // Restore the previous session only if that role still resolves to an account. A
        // stored role whose account has gone is a signed-out app, not a broken one.
        try {
          const stored = window.localStorage.getItem(STORAGE_KEY);
          if (stored && byRole[stored]) {
            setUser(toSessionUser(byRole[stored]));
            window.localStorage.setItem(IDENTITY_KEY, byRole[stored].email);
          }
        } catch {
          // localStorage can throw in private browsing. A signed out app is the right
          // fallback, so there is nothing to do here.
        }
      })
      .catch((err) => {
        if (!alive) return;
        setError(
          err?.message ??
            "Could not load accounts from the API. Is it running, and seeded with the synthetic dataset?",
        );
      })
      .finally(() => {
        if (alive) setReady(true);
      });

    return () => {
      alive = false;
    };
  }, []);

  const apply = useCallback(
    (role: UserRole) => {
      const identity = identities[role];
      if (!identity) {
        setError(`The API has no active ${role} account to act as.`);
        return;
      }
      setUser(toSessionUser(identity));
      setError(null);
      try {
        window.localStorage.setItem(STORAGE_KEY, role);
        // What `lib/api.ts` attaches to every request.
        window.localStorage.setItem(IDENTITY_KEY, identity.email);
      } catch {
        // Not being able to persist the session is survivable for the session itself, but
        // every API call reads the identity from localStorage, so without it nothing loads.
        setError("This browser is blocking local storage, so the API cannot identify you.");
      }
    },
    [identities],
  );

  const signOut = useCallback(() => {
    setUser(null);
    try {
      window.localStorage.removeItem(STORAGE_KEY);
      window.localStorage.removeItem(IDENTITY_KEY);
    } catch {
      // See above.
    }
  }, []);

  const value = useMemo<AuthState>(
    () => ({ user, ready, identities, error, signIn: apply, signOut, switchRole: apply }),
    [user, ready, identities, error, apply, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/**
 * Where each role lands after signing in. See docs/wireframes/01-login.html.
 *
 * Takes the linked player id rather than a whole user because a player is the only role whose
 * landing page depends on anything beyond the role itself.
 */
export function homeFor(role: UserRole, linkedPlayerId?: string | null): string {
  switch (role) {
    case "coach":
      return "/dashboard";
    case "scout":
      return "/search";
    case "federation":
      return "/oversight";
    case "admin":
      return "/integrity";
    case "player":
      // A player account points at its own record. Without a linked player there is nothing
      // to show them, so they land on search and see the empty state rather than a 404.
      return linkedPlayerId ? `/players/${linkedPlayerId}` : "/search";
  }
}

/**
 * Which roles may open which screen. This mirrors the matrix in
 * `docs/wireframes/index.html`. It drives navigation and a friendly redirect only. The API
 * refuses the request independently, because anything enforced only here is not enforced.
 */
export const ROUTE_ROLES: Record<string, UserRole[]> = {
  "/dashboard": ["coach"],
  "/players/new": ["coach"],
  "/search": ["scout", "federation"],
  "/compare": ["coach", "scout", "federation"],
  "/oversight": ["federation", "admin"],
  "/integrity": ["federation", "admin"],
};

export function canAccess(role: UserRole | undefined, path: string): boolean {
  if (!role) return false;
  const key = Object.keys(ROUTE_ROLES).find((r) => path === r || path.startsWith(`${r}/`));
  if (!key) return true;
  return ROUTE_ROLES[key].includes(role);
}
