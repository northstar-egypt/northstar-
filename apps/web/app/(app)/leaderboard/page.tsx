"use client";
/**
 * Academy leaderboard ("find the next pro", part 8): this week's top XP earners among the
 * academy players the caller may see. XP is counted from minutes played and drills done
 * (app/services/journey.py); the API decides who is listed.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, SectionTitle, Skeleton, Table, Td, Th } from "@/components/ui";
import { getLeaderboard } from "@/lib/api";
import type { Leaderboard } from "@/lib/types";

export default function LeaderboardPage() {
  const [data, setData] = useState<Leaderboard | "loading" | "failed">("loading");
  useEffect(() => {
    getLeaderboard().then(setData).catch(() => setData("failed"));
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-bold">Academy leaderboard</h1>
      <Card>
        <SectionTitle>Top XP this week</SectionTitle>
        {data === "loading" ? (
          <Skeleton className="h-24" />
        ) : data === "failed" ? (
          <p className="text-sm text-slate-500">The leaderboard could not be loaded.</p>
        ) : data.items.length === 0 ? (
          <p className="text-sm text-slate-500">No XP earned this week yet. {data.note}</p>
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>#</Th>
                  <Th>Player</Th>
                  <Th>XP</Th>
                  <Th>Minutes</Th>
                  <Th>Drills</Th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((r, i) => (
                  <tr key={r.playerId}>
                    <Td>{i + 1}</Td>
                    <Td>
                      <Link href={`/players/${r.playerId}`} className="font-semibold hover:text-sky-300">
                        <bdi>{r.fullName}</bdi>
                      </Link>
                      <span className="ml-2 text-xs text-slate-400">
                        {[r.position, r.ageLabel].filter(Boolean).join(" · ")}
                      </span>
                    </Td>
                    <Td className="font-semibold text-amber-300">{r.xp}</Td>
                    <Td>{r.minutes}</Td>
                    <Td>{r.drills}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <p className="mt-2 text-xs text-slate-500">{data.note}</p>
          </>
        )}
      </Card>
    </div>
  );
}
