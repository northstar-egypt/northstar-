"use client";

/**
 * Entry point. Sends a signed in user to the home screen for their role and everyone else to
 * the login page. See `homeFor` in lib/auth.ts for the routing table.
 */

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { homeFor, useAuth } from "@/lib/auth";

export default function Home() {
  const { user, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!ready) return;
    router.replace(user ? homeFor(user.role, user.linkedPlayerId) : "/login");
  }, [ready, user, router]);

  return (
    <main className="flex min-h-screen items-center justify-center text-sm text-slate-500">
      Loading
    </main>
  );
}
