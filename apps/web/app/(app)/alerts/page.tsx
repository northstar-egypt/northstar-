"use client";
/**
 * Scout alerts ("find the next pro", part 9): the academy players this user follows against a
 * professional, with an alert where the style match has jumped since they last looked
 * (app/services/journey.py). Following starts from "Watch" on a "Find the next" list.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button, Card, Chip, SectionTitle, Skeleton } from "@/components/ui";
import { getAlerts, markAlertsSeen, unwatchMatch } from "@/lib/api";
import type { MatchAlerts } from "@/lib/types";

export default function AlertsPage() {
  const [data, setData] = useState<MatchAlerts | "loading" | "failed">("loading");
  useEffect(() => {
    getAlerts().then(setData).catch(() => setData("failed"));
  }, []);

  async function seen() {
    setData(await markAlertsSeen());
  }

  async function stop(playerId: string, proId: string) {
    await unwatchMatch(playerId, proId);
    setData(await getAlerts());
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">Alerts</h1>
      <Card>
        <SectionTitle
          action={
            data !== "loading" && data !== "failed" && data.items.some((i) => i.alert) ? (
              <Button onClick={seen}>Mark all as seen</Button>
            ) : null
          }
        >
          Players you watch
        </SectionTitle>
        {data === "loading" ? (
          <Skeleton className="h-24" />
        ) : data === "failed" ? (
          <p className="text-sm text-slate-500">Alerts could not be loaded.</p>
        ) : data.items.length === 0 ? (
          <p className="text-sm text-slate-500">{data.note}</p>
        ) : (
          <>
            <ul className="flex flex-col divide-y divide-slate-800">
              {data.items.map((a) => (
                <li key={`${a.playerId}:${a.proId}`} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span>
                    <Link href={`/players/${a.playerId}`} className="font-semibold hover:text-sky-300">
                      <bdi>{a.fullName}</bdi>
                    </Link>
                    <span className="text-sm text-slate-400"> against </span>
                    <Link href={`/players/${a.proId}`} className="hover:text-sky-300">
                      <bdi>{a.proName}</bdi>
                    </Link>
                  </span>
                  <span className="flex items-center gap-2 text-sm">
                    {a.alert ? <Chip tone="good">Jumped</Chip> : null}
                    <span className="tabular-nums text-slate-300">
                      {a.before ?? "?"}% → {a.now ?? "?"}%
                    </span>
                    <button
                      type="button"
                      className="text-xs text-slate-400 hover:text-rose-300"
                      onClick={() => stop(a.playerId, a.proId)}
                    >
                      Stop watching
                    </button>
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-slate-500">{data.note}</p>
          </>
        )}
      </Card>
    </div>
  );
}
