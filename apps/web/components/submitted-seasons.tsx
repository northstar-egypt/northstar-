"use client";

/**
 * Seasons from approved diaspora submissions (decision 0011): checked by the federation, not
 * from a data source, and never counted in a league comparison. Shown as what they are, with
 * the source the federation checked them against. Draws nothing when there are none.
 */

import { useEffect, useState } from "react";
import { Card, SectionTitle, Table, Td, Th } from "@/components/ui";
import { getSubmittedSeasons } from "@/lib/api";
import type { SubmittedSeasons } from "@/lib/types";

const COUNTS: { key: string; label: string }[] = [
  { key: "appearances", label: "Apps" },
  { key: "minutes_played", label: "Minutes" },
  { key: "goals", label: "Goals" },
  { key: "assists", label: "Assists" },
  { key: "yellow_cards", label: "Yellow" },
  { key: "red_cards", label: "Red" },
];

export function SubmittedSeasonsCard({ playerId }: { playerId: string }) {
  const [data, setData] = useState<SubmittedSeasons | null>(null);
  useEffect(() => {
    let alive = true;
    getSubmittedSeasons(playerId)
      .then((d) => alive && setData(d))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, [playerId]);

  if (!data || data.submissions.length === 0) return null;
  return (
    <Card>
      <SectionTitle>Submitted seasons abroad</SectionTitle>
      {data.note ? <p className="mb-3 text-sm text-slate-400">{data.note}</p> : null}
      <div className="flex flex-col gap-4">
        {data.submissions.map((s) => (
          <div key={s.submissionId}>
            <p className="text-sm text-slate-300">
              {s.clubName} ({s.clubCountry}){s.competition ? `, ${s.competition}` : ""}
              <span className="block text-xs text-slate-500">
                Submitted by a {s.submitterRole}, approved {s.approvedAt ? s.approvedAt.slice(0, 10) : ""}. Source:{" "}
                {/^https?:\/\//i.test(s.sourceUrl) ? (
                  <a href={s.sourceUrl} target="_blank" rel="noopener noreferrer nofollow" className="break-all text-sky-300 hover:underline">
                    {s.sourceUrl}
                  </a>
                ) : (
                  s.sourceUrl
                )}
              </span>
            </p>
            {s.seasons.length ? (
              <Table>
                <thead>
                  <tr>
                    <Th>Season</Th>
                    {COUNTS.map((c) => (
                      <Th key={c.key} className="text-right">
                        {c.label}
                      </Th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {s.seasons.map((x) => (
                    <tr key={`${x.competition}-${x.season}`}>
                      <Td>
                        {x.competition} {x.season}
                      </Td>
                      {COUNTS.map((c) => (
                        <Td key={c.key} className="text-right tabular-nums">
                          {x.metrics[c.key] ?? "n/a"}
                        </Td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <p className="text-xs text-slate-500">No seasons were submitted.</p>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
