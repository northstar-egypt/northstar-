"use client";

/**
 * Session state for the web app.
 *
 * IMPORTANT: this is not authentication. There is no auth endpoint on the API yet. The
 * security workstream's next task is to write the auth decision record and then implement JWT
 * and password hashing, and until that exists this module holds a role in memory and in
 * localStorage so the role-dependent screens can be built and reviewed.
 *
 * What it deliberately does NOT do, because doing it here would be security theatre:
 *   - verify a password
 *   - decide what data the user may see
 *
 * Access control belongs in the API. Every screen in this app treats role as a hint for what
 * to render, never as the enforcement boundary. When the real endpoints land, replace
 * `signIn` with a call that returns a token and a SessionUser, and delete the role switcher.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { DEMO_USERS } from "./fixtures";
import type { SessionUser, UserRole } from "./types";

const STORAGE_KEY = "northstar.devSession";

interface AuthState {
  user: SessionUser | null;
  ready: boolean;
  signIn: (role: UserRole) => void;
  signOut: () => void;
  /** Development only. Goes away with the real auth implementation. */
  switchRole: (role: UserRole) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const role = stored as UserRole;
        if (DEMO_USERS[role]) setUser(DEMO_USERS[role]);
      }
    } catch {
      // localStorage can throw in private browsing modes. A signed out app is the right
      // fallback, so there is nothing to do here.
    }
    setReady(true);
  }, []);

  const apply = useCallback((role: UserRole) => {
    setUser(DEMO_USERS[role]);
    try {
      window.localStorage.setItem(STORAGE_KEY, role);
    } catch {
      // Not being able to persist the session is survivable. It just means a reload signs out.
    }
  }, []);

  const signOut = useCallback(() => {
    setUser(null);
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // See above.
    }
  }, []);

  const value = useMemo<AuthState>(
    () => ({ user, ready, signIn: apply, signOut, switchRole: apply }),
    [user, ready, apply, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** Where each role lands after signing in. See docs/wireframes/01-login.html. */
export function homeFor(role: UserRole): string {
  switch (role) {
    case "coach": return "/dashboard";
    case "scout": return "/search";
    case "federation": return "/oversight";
    case "admin": return "/integrity";
    case "player": return "/players/p-1";
  }
}

/**
 * Which roles may open which screen. This mirrors the matrix in
 * `docs/wireframes/index.html`. It drives navigation and a friendly redirect only. The API
 * must refuse the request independently, because anything enforced only here is not enforced.
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
