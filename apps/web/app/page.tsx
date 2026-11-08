"use client";

/**
 * The front door. A signed-in user goes straight to their role's home (`homeFor` in lib/auth.tsx);
 * everyone else sees what NorthStar is before being asked for a password.
 *
 * It claims only what the product does and links to where each claim can be checked: the story is
 * the backtest's own numbers, and every screen behind the sign-in is the real one.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { homeFor, useAuth } from "@/lib/auth";
import { cx } from "@/lib/format";
import { ROLE_IDENTITY } from "@/lib/roles";

const ROLES = [
  {
    role: "coach" as const,
    headline: "Coaches log",
    body: "Measuring day on a phone at the pitch side, a squad that says who is due a reading, and who is growing fastest.",
  },
  {
    role: "scout" as const,
    headline: "Scouts find",
    body: "Search in Arabic or English, a shortlist, breakouts each season, and scouting reports that put the verdict first.",
  },
  {
    role: "federation" as const,
    headline: "The federation decides",
    body: "Coverage across all 27 governorates, an integrity board for duplicates and fraud, and what the national team needs.",
  },
  {
    role: "player" as const,
    headline: "Players own their record",
    body: "Their progress against their own past, in plain words, and exactly who can see their data.",
  },
];

export default function Home() {
  const { user, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (ready && user) router.replace(homeFor(user.role));
  }, [ready, user, router]);

  if (!ready || user) {
    return <main className="min-h-screen" />;
  }

  return (
    <main className="min-h-screen">
      <div className="mx-auto flex max-w-6xl flex-col gap-20 px-4 py-10 sm:py-14">
        <header className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-2 text-lg font-bold tracking-tight">
            <span className="inline-block h-3 w-3 rotate-45 bg-sky-400" aria-hidden />
            NorthStar
          </span>
          <Link href="/login" className="rounded-lg border border-slate-700 px-4 py-1.5 text-sm hover:bg-slate-900">
            Sign in
          </Link>
        </header>

        <section className="max-w-3xl">
          <p className="text-sm font-medium uppercase tracking-widest text-sky-400">Egyptian sports talent</p>
          <h1 className="mt-4 text-4xl font-bold leading-[1.1] tracking-tight sm:text-6xl">
            In Egypt, talent is found by chance. NorthStar finds it by system.
          </h1>
          <p className="mt-6 max-w-2xl text-lg text-slate-400">
            A national record of every player, kept over years, read by models that are graded on how often they are
            right, and shown to each person in the way their job needs.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/story"
              className="rounded-full bg-sky-500 px-6 py-3 text-sm font-semibold text-slate-950 hover:bg-sky-400"
            >
              See the boy a size cut would have released
            </Link>
            <Link href="/login" className="rounded-full border border-slate-700 px-6 py-3 text-sm font-semibold hover:bg-slate-900">
              Sign in
            </Link>
          </div>
        </section>

        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {ROLES.map(({ role, headline, body }) => {
            const identity = ROLE_IDENTITY[role];
            return (
              <div key={role} className={cx("rounded-2xl border border-l-4 border-slate-800 bg-slate-900/60 p-6", identity.border)}>
                <span className={cx("inline-block h-2.5 w-2.5 rotate-45", identity.mark)} aria-hidden />
                <h2 className="mt-3 text-lg font-semibold">{headline}</h2>
                <p className="mt-2 text-sm leading-relaxed text-slate-400">{body}</p>
              </div>
            );
          })}
        </section>

        <section className="grid gap-10 md:grid-cols-2">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Two sports, one engine</h2>
            <p className="mt-3 text-slate-400">
              Football and table tennis run on the same core: identity, measurements over time, consent and access. What
              differs is a sport module, a file of definitions. Adding a sport is a configuration change, not a rebuild.
            </p>
          </div>
          <div>
            <h2 className="text-2xl font-bold tracking-tight">It never invents a number</h2>
            <p className="mt-3 text-slate-400">
              A forecast comes with its range or not at all. A percentile from too few players is left out. Every model is
              scored against an answer key, and the scores that came out worse than hoped are published with the rest.
            </p>
          </div>
        </section>

        <footer className="border-t border-slate-800 pt-6 text-sm text-slate-500">
          A graduation project. Every player in this prototype is synthetic: no real person&apos;s data is used.
        </footer>
      </div>
    </main>
  );
}
