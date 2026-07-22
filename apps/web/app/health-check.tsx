"use client";

import { useEffect, useState } from "react";

// The API base URL. Defaults to the local docker-compose mapping. Overridable per
// environment via NEXT_PUBLIC_API_URL (see .env.example at the repo root).
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Status = "checking" | "ok" | "error";

/**
 * Small connectivity widget. Calls the API's /health/db endpoint on mount and reports
 * whether the backend and database are reachable. Its whole job is to prove the local
 * stack is wired together correctly. Replace with real UI as features land.
 */
export function HealthCheck() {
  const [status, setStatus] = useState<Status>("checking");
  const [detail, setDetail] = useState<string>("");

  useEffect(() => {
    fetch(`${API_URL}/health/db`)
      .then((res) => res.json())
      .then((data) => {
        const healthy = data.status === "ok";
        setStatus(healthy ? "ok" : "error");
        setDetail(data.database ?? "");
      })
      .catch(() => {
        setStatus("error");
        setDetail("API unreachable");
      });
  }, []);

  const color =
    status === "ok"
      ? "text-emerald-400"
      : status === "error"
        ? "text-red-400"
        : "text-slate-400";

  const label =
    status === "checking"
      ? "Checking API and database..."
      : status === "ok"
        ? "API and database reachable"
        : `Not reachable (${detail})`;

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-3 text-sm">
      <span className={`font-medium ${color}`}>{label}</span>
      <div className="mt-1 text-xs text-slate-500">
        Checking{" "}
        <a
          href={`${API_URL}/health/db`}
          className="underline hover:text-slate-300"
          target="_blank"
          rel="noreferrer"
        >
          {API_URL}/health/db
        </a>
      </div>
    </div>
  );
}
