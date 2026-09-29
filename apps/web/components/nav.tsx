"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ROUTE_ROLES, homeFor, useAuth } from "@/lib/auth";
import { cx } from "@/lib/format";
import type { UserRole } from "@/lib/types";

const LINKS: { href: string; label: string }[] = [
  { href: "/dashboard", label: "Squad" },
  { href: "/search", label: "Search" },
  { href: "/compare", label: "Compare" },
  { href: "/oversight", label: "Oversight" },
  { href: "/integrity", label: "Integrity" },
];

const ROLES: UserRole[] = ["coach", "scout", "federation", "player", "admin"];

export function Nav() {
  const { user, demoAccounts, signInAs, signOut } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  if (!user) return null;

  const visible = LINKS.filter((l) => {
    const allowed = ROUTE_ROLES[l.href];
    return !allowed || allowed.includes(user.role);
  });

  return (
    <header className="sticky top-0 z-20 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
        <Link href={homeFor(user.role, user.linkedPlayerId)} className="flex items-center gap-2 font-bold tracking-tight">
          <span className="inline-block h-2.5 w-2.5 rotate-45 bg-sky-400" aria-hidden />
          NorthStar
        </Link>

        <nav className="flex flex-wrap items-center gap-1" aria-label="Main">
          {visible.map((l) => {
            const active = pathname === l.href || pathname.startsWith(`${l.href}/`);
            return (
              <Link
                key={l.href}
                href={l.href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "rounded-md px-2.5 py-1 text-sm transition",
                  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400",
                  active
                    ? "bg-slate-800 font-semibold text-slate-100"
                    : "text-slate-400 hover:bg-slate-900 hover:text-slate-200",
                )}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {user.organizationName ? (
            <span className="hidden text-xs text-slate-500 sm:inline">{user.organizationName}</span>
          ) : null}

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
                    router.push(homeFor(session.role, session.linkedPlayerId));
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

      <div className="border-t border-amber-900/40 bg-amber-950/30 px-4 py-1 text-center text-[0.7rem] text-amber-300/90">
        Prototype. All player data is synthetic.
      </div>
    </header>
  );
}
