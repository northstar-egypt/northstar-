"use client";

/**
 * Compact API and database connectivity indicator.
 *
 * This started as the landing page widget whose whole job was proving the docker-compose stack
 * was wired together. That job still matters, so it lives on in the app shell footer where a
 * developer can see at a glance whether the backend is up. It is the only thing in this app
 * that calls a real endpoint.
 */

import { useEffect, useState } from "react";
import { API_URL, getHealth } from "@/lib/api";

type State = "checking" | "ok" | "error";

export function ApiStatus() {
  const [state, setState] = useState<State>("checking");
  const [detail, setDetail] = useState("");

  useEffect(() => {
    let alive = true;
    getHealth().then((h) => {
      if (!alive) return;
      setState(h.ok ? "ok" : "error");
      setDetail(h.detail);
    });
    return () => {
      alive = false;
    };
  }, []);

  const color =
    state === "ok" ? "bg-emerald-400" : state === "error" ? "bg-rose-400" : "bg-slate-500";
  const label =
    state === "checking"
      ? "checking API"
      : state === "ok"
        ? "API and database reachable"
        : `API not reachable${detail ? `, ${detail}` : ""}`;

  return (
    <a
      href={`${API_URL}/health/db`}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300"
    >
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${color}`} aria-hidden />
      {label}
    </a>
  );
}
