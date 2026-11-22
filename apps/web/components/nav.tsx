"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ROUTE_ROLES, homeFor, useAuth } from "@/lib/auth";
import { cx } from "@/lib/format";
import { ROLE_IDENTITY } from "@/lib/roles";
import type { UserRole } from "@/lib/types";
import { LayoutDirection } from "@/components/layout-direction";

const LINKS: { href: string; label: string }[] = [
  { href: "/scout", label: "Home" },
  { href: "/me", label: "Home" },
  { href: "/dashboard", label: "Home" },
  { href: "/oversight", label: "Home" },
  { href: "/search", label: "Search" },
  { href: "/compare", label: "Compare" },
  { href: "/explore", label: "Explore" },
  { href: "/gaps", label: "Team gaps" },
  { href: "/ask", label: "Ask" },
  { href: "/integrity", label: "Integrity" },
];

const ROLES: UserRole[] = ["coach", "scout", "federation", "player", "admin"];

export function Nav() {
  const { user, demoAccounts, signInAs, signOut } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  if (!user) return null;
  const identity = ROLE_IDENTITY[user.role];

  const visible = LINKS.filter((l) => {
    const allowed = ROUTE_ROLES[l.href];
    return !allowed || allowed.includes(user.role);
  });

  return (
    <header className="app-navigation sticky top-0 z-20 border-b border-slate-700 bg-slate-950/95 backdrop-blur lg:fixed lg:inset-y-0 lg:start-0 lg:w-60 lg:overflow-y-auto lg:border-b-0 lg:border-e">
      <div className="mx-auto flex h-full max-w-6xl flex-wrap items-center gap-x-4 gap-y-3 px-4 py-4 lg:h-auto lg:min-h-full lg:flex-col lg:items-stretch lg:gap-7 lg:px-5 lg:py-7">
        <Link href={homeFor(user.role)} className="flex items-center gap-2 font-bold tracking-tight">
          <span className={cx("inline-block h-2.5 w-2.5 rotate-45", identity.mark)} aria-hidden />
          NorthStar
          <span className={cx("rounded-md border border-slate-700 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide", identity.text)}>{identity.title}</span>
        </Link>

        <nav className="order-last flex w-full gap-1 overflow-x-auto pb-1 lg:order-none lg:flex-col lg:overflow-visible" aria-label="Main">
          {visible.map((l) => {
            const active = pathname === l.href || pathname.startsWith(`${l.href}/`);
            return (
              <Link
                key={l.href}
                href={l.href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "flex min-h-11 shrink-0 items-center gap-3 whitespace-nowrap rounded-lg px-3 py-2.5 text-sm font-medium transition",
                  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400",
                  active
                    ? identity.active
                    : "text-slate-400 hover:bg-slate-900 hover:text-slate-200",
                )}
              >
                <span aria-hidden="true" className={cx("hidden h-1.5 w-1.5 rounded-full lg:block", active ? identity.mark : "bg-slate-600")} />
                {l.label}
              </Link>
            );
          })}
        </nav>

        <div className="ms-auto flex flex-wrap items-center gap-2 lg:ms-0 lg:mt-auto lg:flex-col lg:items-stretch lg:border-t lg:border-slate-800 lg:pt-5">
          {user.organizationName ? (
            <span className="hidden text-xs text-slate-500 sm:inline">{user.organizationName}</span>
          ) : null}
          <LayoutDirection />

          {/*
            Development only, and only when the API lists demo accounts. Switching signs in
            for real as that role's demo account, so a reviewer can see every role's view.
          */}
          {Object.keys(demoAccounts).length ? (
            <label className="flex items-center gap-1.5">
              <span className="sr-only">Switch demo account, development only</span>
              <select
                value={user.role}
                onChange={async (e) => {
                  const role = e.target.value as UserRole;
                  try {
                    const session = await signInAs(role);
                    router.push(homeFor(session.role));
                  } catch {
                    // The demo account could not sign in. Staying on the current session is the
                    // honest outcome; the select snaps back because `user` did not change.
                  }
                }}
                className="rounded-md border border-dashed border-amber-800 bg-amber-950/40 px-2 py-1 text-xs text-amber-200 focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
                title="Development only. Signs in as the demo account for the chosen role."
              >
                {ROLES.filter((r) => demoAccounts[r]).map((r) => (
                  <option key={r} value={r} className="bg-slate-900 text-slate-100">
                    {r}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          <button
            type="button"
            onClick={async () => {
              await signOut();
              router.push("/login");
            }}
            className="rounded-md px-2 py-1 text-xs text-slate-400 hover:bg-slate-900 hover:text-slate-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
          >
            Sign out
          </button>
        </div>
      </div>

      <div className={cx("h-0.5 lg:hidden", identity.bar)} aria-hidden />
    </header>
  );
}
