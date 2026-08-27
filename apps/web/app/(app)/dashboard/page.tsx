"use client";

/**
 * Coach dashboard. See docs/wireframes/02-coach-dashboard.html.
 *
 * The screen answers one question on arrival: who needs my attention today. Everything else is
 * secondary, which is why the default sort is by attention rather than by name, and why the
 * overdue count is promoted over squad size. A squad size never changes and tells a coach
 * nothing.
 */

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Sparkline } from "@/components/charts";
import {
  Avatar,
  Button,
  Card,
  Chip,
  Empty,
  SectionTitle,
  Skeleton,
  Stat,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { getSquad } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { STALE_DAYS, cx, daysLabel, isStale } from "@/lib/format";
import type { SquadRow } from "@/lib/types";

type Filter = "all" | "overdue" | "consent" | "flagged";

export default function DashboardPage() {
  const { user } = useAuth();
  const [rows, setRows] = useState<SquadRow[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    let alive = true;
    getSquad().then((r) => alive && setRows(r));
    return () => {
      alive = false;
    };
  }, []);

  const counts = useMemo(() => {
    if (!rows) return { overdue: 0, consent: 0, flagged: 0 };
    return {
      overdue: rows.filter((r) => isStale(r.daysSinceLastLog)).length,
      consent: rows.filter((r) => !r.consentComplete).length,
      flagged: rows.filter((r) => r.flags.some((f) => f.type !== "consent")).length,
    };
  }, [rows]);

  const visible = useMemo(() => {
    if (!rows) return [];
    const filtered = rows.filter((r) => {
      if (filter === "overdue") return isStale(r.daysSinceLastLog);
      if (filter === "consent") return !r.consentComplete;
      if (filter === "flagged") return r.flags.some((f) => f.type !== "consent");
      return true;
    });
    // Attention first: the stalest records at the top, because this is a work queue.
    return [...filtered].sort((a, b) => (b.daysSinceLastLog ?? 9999) - (a.daysSinceLastLog ?? 9999));
  }, [rows, filter]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Squad</h1>
          <p className="text-sm text-slate-500">
            {user?.organizationName}
            {rows ? `, ${rows.length} players` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/compare">
            <Button variant="ghost">Compare players</Button>
          </Link>
          <Link href="/players/new">
            <Button variant="primary">Add player</Button>
          </Link>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {rows ? (
          <>
            <Stat label="Squad size" value={rows.length} />
            <Stat
              label={`Not measured in ${STALE_DAYS} days`}
              value={counts.overdue}
              tone={counts.overdue > 0 ? "warn" : "good"}
              hint="drives the default sort"
            />
            <Stat
              label="Consent missing"
              value={counts.consent}
              tone={counts.consent > 0 ? "warn" : "good"}
            />
            <Stat label="Flags to review" value={counts.flagged} />
          </>
        ) : (
          Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[5.5rem]" />)
        )}
      </div>

      {rows && (counts.overdue > 0 || counts.consent > 0 || counts.flagged > 0) ? (
        <Card className="border-amber-900/50 bg-amber-950/20">
          <SectionTitle>Needs you first</SectionTitle>
          <div className="flex flex-wrap gap-2">
            {counts.overdue > 0 ? (
              <Chip tone="warn" onClick={() => setFilter("overdue")} active={filter === "overdue"}>
                {counts.overdue} not measured in {STALE_DAYS} days
              </Chip>
            ) : null}
            {counts.consent > 0 ? (
              <Chip tone="warn" onClick={() => setFilter("consent")} active={filter === "consent"}>
                {counts.consent} minors without guardian consent
              </Chip>
            ) : null}
            {counts.flagged > 0 ? (
              <Chip tone="warn" onClick={() => setFilter("flagged")} active={filter === "flagged"}>
                {counts.flagged} flagged by the models
              </Chip>
            ) : null}
            {filter !== "all" ? (
              <Chip onClick={() => setFilter("all")}>clear filter</Chip>
            ) : null}
          </div>
        </Card>
      ) : null}

      <Card>
        <SectionTitle
          action={
            <span className="text-xs text-slate-500">
              sorted by longest since last measurement
            </span>
          }
        >
          {filter === "all" ? "All players" : `Filtered, ${visible.length} players`}
        </SectionTitle>

        {!rows ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : visible.length === 0 ? (
          <Empty>Nothing here. That is a good state, not a bug.</Empty>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th />
                <Th>Player</Th>
                <Th>Pos</Th>
                <Th>Age</Th>
                <Th>Height</Th>
                <Th>Last logged</Th>
                <Th>Trend</Th>
                <Th>Flags</Th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr key={r.player.id} className="hover:bg-slate-900/40">
                  <Td className="w-9">
                    <Avatar size={28} />
                  </Td>
                  <Td>
                    <Link
                      href={`/players/${r.player.id}`}
                      className="font-semibold text-slate-100 hover:text-sky-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
                    >
                      {r.player.fullName}
                    </Link>
                  </Td>
                  <Td>{r.player.position}</Td>
                  <Td className="tabular-nums">{r.ageLabel}</Td>
                  <Td className="tabular-nums">{r.heightCm ? `${r.heightCm} cm` : "no data"}</Td>
                  <Td
                    className={cx(
                      "tabular-nums",
                      isStale(r.daysSinceLastLog) && "font-semibold text-amber-400",
                    )}
                  >
                    {daysLabel(r.daysSinceLastLog)}
                  </Td>
                  <Td>
                    <Sparkline values={r.heightTrend} />
                  </Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      {r.flags.map((f) => (
                        <Chip key={f.type} tone={f.type === "consent" ? "warn" : "brand"}>
                          {f.label}
                        </Chip>
                      ))}
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
