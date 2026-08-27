"use client";

/**
 * Shell for every signed in screen: navigation, plus a redirect for roles that have no business
 * on the current route.
 *
 * The redirect is a courtesy, not a security control. A determined user can reach any route by
 * typing it. What stops them seeing data they should not see is the API refusing the request,
 * which is the security workstream's job. Nothing here should ever be the only thing standing
 * between a role and a record.
 */

import { useRouter, usePathname } from "next/navigation";
import { useEffect } from "react";
import { ApiStatus } from "@/components/api-status";
import { Nav } from "@/components/nav";
import { canAccess, homeFor, useAuth } from "@/lib/auth";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, ready } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!ready) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if (!canAccess(user.role, pathname)) {
      router.replace(homeFor(user.role));
    }
  }, [ready, user, pathname, router]);

  if (!ready || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        Loading
      </div>
    );
  }

  if (!canAccess(user.role, pathname)) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4 text-center text-sm text-slate-400">
        This screen is not part of the {user.role} role. Taking you back.
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
      <footer className="border-t border-slate-900 px-4 py-3">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2">
          <ApiStatus />
          <span className="text-xs text-slate-600">
            Wireframes in <span className="font-mono">docs/wireframes</span>
          </span>
        </div>
      </footer>
    </div>
  );
}
