"use client";

/**
 * Session state for the web app.
 *
 * The session itself is an HttpOnly cookie the API sets at sign-in (see `lib/api.ts` and
 * `apps/api/app/security.py`). This module never sees the token. It asks the API `/me` who
 * the session belongs to, and keeps that answer for the screens to render from.
 *
 * What it deliberately does NOT do:
 *   - decide what data the user may see. The API does that, in
 *     `apps/api/app/services/access.py`. Every screen treats the role as a hint for what to
 *     render, never as the enforcement boundary.
 *   - store anything about the session in localStorage, where a script could read it.
 *
 * Demo accounts: in development the API lists one synthetic account per role with the
 * published demo password (`/dev/identities`). `signInAs` signs in as one of them through the
 * real `POST /auth/login`, so the demo buttons exercise exactly the path a real user takes.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  getDevIdentities,
  getSession,
  login,
  logout,
  type DevIdentity,
} from "./api";
import type { SessionUser, UserRole } from "./types";

interface AuthState {
  user: SessionUser | null;
  /** False until the API has answered whether there is a session. */
  ready: boolean;
  /** Demo accounts by role. Empty outside development or when the API is unreachable. */
  demoAccounts: Record<string, DevIdentity>;
  /** Set when the API could not be reached at all, so the login screen can say why. */
  error: string | null;
  /** Resolves with the signed-in user, or rejects with the API's message. */
  signIn: (email: string, password: string) => Promise<SessionUser>;
  /** Development only: sign in as the demo account for a role. */
  signInAs: (role: UserRole) => Promise<SessionUser>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [demoAccounts, setDemoAccounts] = useState<Record<string, DevIdentity>>({});
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let alive = true;

    // Is there already a session? A 401 just means signed out.
    getSession()
      .then((session) => {
        if (alive) setUser(session);
      })
      .catch((err) => {
        if (!alive) return;
        if (!(err instanceof ApiError && err.isAuth)) {
          setError(err?.message ?? "Could not reach the API. Is it running?");
        }
      })
      .finally(() => {
        if (alive) setReady(true);
      });

    // Demo accounts exist only in development. Anything else, including a 404, means none.
    getDevIdentities()
      .then((rows) => {
        if (!alive) return;
        const byRole: Record<string, DevIdentity> = {};
        for (const row of rows) byRole[row.role] = row;
        setDemoAccounts(byRole);
      })
      .catch(() => {
        if (alive) setDemoAccounts({});
      });

    return () => {
      alive = false;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const session = await login(email, password);
    setUser(session);
    setError(null);
    return session;
  }, []);

  const signInAs = useCallback(
    async (role: UserRole) => {
      const account = demoAccounts[role];
      if (!account) throw new Error(`There is no active ${role} demo account.`);
      return signIn(account.email, account.demoPassword);
    },
    [demoAccounts, signIn],
  );

  const signOut = useCallback(async () => {
    try {
      await logout();
    } finally {
      // Signed out on screen even if the request failed: the cookie expires on its own, and
      // a user who clicked "sign out" must not be left looking at the previous session.
      setUser(null);
    }
  }, []);

  const value = useMemo<AuthState>(
    () => ({ user, ready, demoAccounts, error, signIn, signInAs, signOut }),
    [user, ready, demoAccounts, error, signIn, signInAs, signOut],
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
