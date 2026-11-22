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
import { Skeleton } from "@/components/ui";

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
        <Skeleton className="h-24 w-64" />
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
    <div className="app-shell flex min-h-screen flex-col lg:ps-60">
      <a href="#main-content" className="skip-link">Skip to content</a>
      <Nav />
      <div className="workspace-heading border-b border-slate-800 px-4 py-3 sm:px-8">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
          <span>NorthStar <span aria-hidden="true" className="mx-2 text-slate-600">/</span> Talent intelligence</span>
          <span className="text-amber-200">Prototype · Youth records are synthetic · Pro sources: FootyStats / StatsBomb</span>
        </div>
      </div>
      <main id="main-content" tabIndex={-1} className="workspace-main mx-auto w-full min-w-0 max-w-6xl flex-1 px-4 py-7 sm:px-8 sm:py-10">{children}</main>
      <footer className="app-footer border-t border-slate-800 px-4 py-4 sm:px-8">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2">
          <ApiStatus />
        </div>
      </footer>
    </div>
  );
}
