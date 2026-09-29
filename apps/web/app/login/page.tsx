"use client";

/**
 * Login. See docs/wireframes/01-login.html.
 *
 * The form signs in through `POST /auth/login`. On success the API sets an HttpOnly session
 * cookie and this page routes by role. A wrong email and a wrong password get the same
 * message from the API, and this page shows it as-is, so the form cannot be used to discover
 * which accounts exist.
 *
 * In development the page also offers one demo account per role. Those buttons sign in through
 * the same endpoint with the published demo password; they only save typing. Outside
 * development the API does not list demo accounts and the section does not render.
 *
 * Deliberately absent: a "stay signed in" control. Sessions last a fixed 8 hours and end
 * sooner if the account is deactivated. A longer-lived "remember me" session would need a
 * revocable server-side session store first (see docs/threat-model.md).
 */

import { useRouter } from "next/navigation";
import { useState } from "react";
import { homeFor, useAuth } from "@/lib/auth";
import { Button, Card, Label, inputClass } from "@/components/ui";
import type { UserRole } from "@/lib/types";

const DEMO: { role: UserRole; label: string; blurb: string }[] = [
  { role: "coach", label: "Coach", blurb: "Logs and edits their own squad" },
  { role: "scout", label: "Scout", blurb: "Searches across scope, cannot edit" },
  { role: "federation", label: "Federation", blurb: "National oversight and the integrity queue" },
  { role: "player", label: "Player", blurb: "Sees only their own profile" },
];

export default function LoginPage() {
  const { signIn, signInAs, demoAccounts, error: apiError } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function finish(attempt: Promise<{ role: UserRole; linkedPlayerId?: string | null }>) {
    setBusy(true);
    setError(null);
    try {
      const session = await attempt;
      router.push(homeFor(session.role, session.linkedPlayerId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in.");
      setBusy(false);
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    void finish(signIn(email, password));
  }

  const demos = DEMO.filter((d) => demoAccounts[d.role]);
  const demoPassword = Object.values(demoAccounts)[0]?.demoPassword;

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-7 flex flex-col items-center gap-1.5 text-center">
          <span className="inline-block h-4 w-4 rotate-45 bg-sky-400" aria-hidden />
          <h1 className="text-2xl font-bold tracking-tight">NorthStar</h1>
          <p className="text-xs uppercase tracking-[0.14em] text-slate-500">
            Egyptian sports talent
          </p>
        </div>

        <Card>
          <form onSubmit={submit} className="flex flex-col gap-3.5">
            <div className="flex flex-col gap-1">
              <Label>Email</Label>
              <input
                type="email"
                aria-label="Email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@club.eg"
                autoComplete="username"
                required
                className={inputClass}
              />
            </div>

            <div className="flex flex-col gap-1">
              <Label>Password</Label>
              <input
                type="password"
                aria-label="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                className={inputClass}
              />
            </div>

            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? "Signing in" : "Sign in"}
            </Button>

            {/* One error slot, reserved in the layout so the form does not jump. */}
            <div className="min-h-[2.5rem]" aria-live="polite">
              {error || apiError ? (
                <p className="rounded-md border border-amber-900/70 bg-amber-950/40 px-3 py-2 text-xs text-amber-200">
                  {error ?? apiError}
                </p>
              ) : null}
            </div>
          </form>
        </Card>

        {demos.length ? (
          <section className="mt-5">
            <h2 className="mb-1 text-[0.66rem] font-medium uppercase tracking-[0.12em] text-slate-500">
              Demo accounts, development only
            </h2>
            <p className="mb-2 text-xs text-slate-500">
              Synthetic accounts. Each button signs in for real with the demo password
              {demoPassword ? (
                <>
                  {" "}
                  <span className="font-mono text-slate-400">{demoPassword}</span>
                </>
              ) : null}
              .
            </p>
            <ul className="flex flex-col gap-1.5">
              {demos.map((d) => {
                const account = demoAccounts[d.role];
                return (
                  <li key={d.role}>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void finish(signInAs(d.role))}
                      className="w-full rounded-md border border-slate-800 bg-slate-900/50 px-3 py-2 text-left transition hover:border-slate-600 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
                    >
                      <span className="text-sm font-semibold text-slate-100">{d.label}</span>
                      <span className="block text-xs text-slate-500">{d.blurb}</span>
                      {account.organizationName ? (
                        // Organization names are often Arabic; `dir="auto"` keeps them readable.
                        <span dir="auto" className="block text-xs text-slate-400">
                          {account.organizationName}
                        </span>
                      ) : null}
                      <span className="block font-mono text-[0.7rem] text-slate-600">
                        {account.email}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}

        <p className="mt-5 border-t border-slate-800 pt-4 text-center text-xs text-slate-500">
          Are you a player who wants to be listed?{" "}
          <span className="text-slate-400 underline decoration-dotted" title="Not designed yet.">
            Submit your profile
          </span>
        </p>
      </div>
    </main>
  );
}
