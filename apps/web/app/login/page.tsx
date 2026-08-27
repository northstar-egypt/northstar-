"use client";

/**
 * Login. See docs/wireframes/01-login.html.
 *
 * There is no auth endpoint yet, so submitting this form does not verify anything. It picks a
 * demo session so the role-dependent screens can be reviewed. Everything about the layout,
 * the single error slot, and the routing by role is real and survives the switch to real auth.
 *
 * Deliberately absent: a "stay signed in" control. The wireframe drew one, and then the open
 * question underneath it pointed out that what it means depends entirely on whether sessions
 * end up token based or cookie based. Drawing a control we cannot honour would be a promise we
 * have not earned, so it waits for the security track's decision record.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";
import { homeFor, useAuth } from "@/lib/auth";
import { Button, Card, Label, inputClass } from "@/components/ui";
import type { UserRole } from "@/lib/types";

const DEMO: { role: UserRole; label: string; blurb: string }[] = [
  { role: "coach", label: "Coach", blurb: "Zamalek Academy, logs and edits their own squad" },
  { role: "scout", label: "Scout", blurb: "Searches across scope, cannot edit" },
  { role: "federation", label: "Federation", blurb: "National oversight and the integrity queue" },
  { role: "player", label: "Player", blurb: "Sees only their own profile" },
];

export default function LoginPage() {
  const { signIn } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);

    // TODO(api): POST /auth/login, returning a token and a SessionUser.
    // Blocked on the security workstream's auth decision record.
    window.setTimeout(() => {
      setBusy(false);
      setError(
        "Sign in is not built yet. The API has no auth endpoint. Pick a demo role below to see the screens.",
      );
    }, 350);
  }

  function useDemo(role: UserRole) {
    signIn(role);
    router.push(homeFor(role));
  }

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
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@club.eg"
                autoComplete="username"
                className={inputClass}
              />
            </div>

            <div className="flex flex-col gap-1">
              <Label>Password</Label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                className={inputClass}
              />
            </div>

            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? "Checking" : "Sign in"}
            </Button>

            {/*
              One error slot, reserved in the layout so the form does not jump. A wrong email
              and a wrong password must produce the same message, so the form cannot be used to
              discover which accounts exist.
            */}
            <div className="min-h-[2.5rem]" aria-live="polite">
              {error ? (
                <p className="rounded-md border border-amber-900/70 bg-amber-950/40 px-3 py-2 text-xs text-amber-200">
                  {error}
                </p>
              ) : null}
            </div>
          </form>
        </Card>

        <section className="mt-5">
          <h2 className="mb-2 text-[0.66rem] font-medium uppercase tracking-[0.12em] text-slate-500">
            Demo roles, development only
          </h2>
          <ul className="flex flex-col gap-1.5">
            {DEMO.map((d) => (
              <li key={d.role}>
                <button
                  type="button"
                  onClick={() => useDemo(d.role)}
                  className="w-full rounded-md border border-slate-800 bg-slate-900/50 px-3 py-2 text-left transition hover:border-slate-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
                >
                  <span className="text-sm font-semibold text-slate-100">{d.label}</span>
                  <span className="block text-xs text-slate-500">{d.blurb}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>

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
