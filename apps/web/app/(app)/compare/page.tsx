"use client";

/**
 * Comparison. See docs/wireframes/06-comparison.html.
 *
 * The toggle between comparing by birthday and comparing by maturity is the screen, not a
 * feature on it. Every academy that cuts a player in the wrong month does it because they only
 * ever saw the first view.
 *
 * The rule that matters most here: where two estimates differ by less than their uncertainty,
 * the interface reports that they are indistinguishable instead of ranking them. Drawing one as
 * better would be the exact failure this product exists to fix.
 */

import { useEffect, useMemo, useState } from "react";
import { OverlaidGrowth, RADAR_COLOURS, Radar } from "@/components/charts";
import {
  Avatar,
  Banner,
  Card,
  Chip,
  Empty,
  SectionTitle,
  Skeleton,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { useSearchParams } from "next/navigation";
import { getComparison, getRadar } from "@/lib/api";
import { cx } from "@/lib/format";
import type { Comparison, PlayerRadar } from "@/lib/types";

export default function ComparePage() {
  const [basis, setBasis] = useState<"age" | "maturity">("age");
  const [data, setData] = useState<Comparison | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Players come from the query string, which is what the player profile's Compare button
  // builds: /compare?players=<id>&players=<id>, or a single comma-separated value.
  const params = useSearchParams();
  const playerIds = useMemo(() => {
    const raw = params.getAll("players").flatMap((value) => value.split(","));
    return raw.map((value) => value.trim()).filter(Boolean);
  }, [params]);

  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);

    if (playerIds.length < 2) {
      setError(
        playerIds.length === 0
          ? "Pick players to compare from a player profile or from search."
          : "Comparison needs at least two players. Add another from search.",
      );
      return;
    }

    getComparison(playerIds, basis)
      .then((c) => alive && setData(c))
      .catch((err) => alive && setError(err.message));
    return () => {
      alive = false;
    };
  }, [basis, playerIds]);

  if (error) {
    return (
      <Card>
        <p className="text-sm text-slate-400">{error}</p>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold tracking-tight">
          Comparing {data ? data.players.length : ""} players
        </h1>
        <div
          className="flex gap-1.5"
          role="group"
          aria-label="Comparison basis"
        >
          <Chip onClick={() => setBasis("age")} active={basis === "age"}>
            by age
          </Chip>
          <Chip onClick={() => setBasis("maturity")} active={basis === "maturity"}>
            by maturity
          </Chip>
        </div>
      </div>

      {!data ? (
        <>
          <Skeleton className="h-16" />
          <Skeleton className="h-48" />
          <Skeleton className="h-64" />
        </>
      ) : (
        <>
          {data.caveat ? <Banner tone="warn">{data.caveat}</Banner> : null}

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data.players.map((entry) => (
              <Card key={entry.player.id} className="flex items-center gap-3">
                <Avatar size={40} />
                <div className="min-w-0">
                  <p className="truncate font-semibold">{entry.player.fullName}</p>
                  <p className="text-xs text-slate-500">
                    {entry.ageLabel} &middot; {entry.player.position}
                  </p>
                  {entry.maturityOffsetYears != null ? (
                    <p className="text-xs text-slate-500">
                      maturity {entry.maturityOffsetYears > 0 ? "+" : ""}
                      {entry.maturityOffsetYears.toFixed(1)} yr
                    </p>
                  ) : null}
                </div>
              </Card>
            ))}
            {data.players.length < 3 ? (
              <Card className="flex items-center justify-center border-dashed text-sm text-slate-600">
                Add a third player
              </Card>
            ) : null}
          </div>

          <Card>
            <SectionTitle>Growth curves, overlaid</SectionTitle>
            {data.growth.length > 0 ? (
              <OverlaidGrowth
                series={data.growth}
                labels={data.players.map((p) => p.player.fullName)}
              />
            ) : (
              <Empty>No growth data for these players.</Empty>
            )}
          </Card>

          <CompareRadar
            players={data.players.map((p) => ({
              id: p.player.id,
              name: p.player.fullName,
              sport: p.player.primarySport,
            }))}
          />

          <Card>
            <SectionTitle>Side by side</SectionTitle>
            <Table>
              <thead>
                <tr>
                  <Th>Metric</Th>
                  {data.players.map((p) => (
                    <Th key={p.player.id}>{p.player.fullName}</Th>
                  ))}
                  <Th>Difference</Th>
                </tr>
              </thead>
              <tbody>
                {data.metrics.map((m) => {
                  const values = m.values;
                  const valid = values.filter((v): v is number => v != null);
                  const best = m.higherIsBetter ? Math.max(...valid) : Math.min(...valid);
                  const diff =
                    valid.length >= 2 ? Math.abs(Math.max(...valid) - Math.min(...valid)) : null;

                  return (
                    <tr key={m.label}>
                      <Td className="whitespace-nowrap">
                        {m.label}
                        {m.unit ? <span className="text-slate-600"> ({m.unit})</span> : null}
                      </Td>
                      {values.map((v, i) => (
                        <Td
                          key={i}
                          className={cx(
                            "tabular-nums",
                            // Emphasis marks the better value per metric, which is not always
                            // the larger one. Sprint time is the obvious counterexample.
                            !m.indistinguishable && v === best && "font-semibold text-slate-100",
                          )}
                        >
                          {v == null ? "no data" : v}
                        </Td>
                      ))}
                      <Td>
                        {m.indistinguishable ? (
                          <Chip tone="warn" title={m.note}>
                            overlapping
                          </Chip>
                        ) : diff != null ? (
                          <span className="tabular-nums text-slate-400">
                            {diff.toFixed(diff < 10 ? 2 : 0)}
                          </span>
                        ) : (
                          "-"
                        )}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>

            {data.metrics.some((m) => m.indistinguishable) ? (
              <p className="mt-3 rounded-md border border-amber-900/50 bg-amber-950/20 px-3 py-2 text-xs text-amber-200">
                {data.metrics.find((m) => m.indistinguishable)?.note} Two forecasts that differ by
                less than their uncertainty are not different, so this row is reported rather than
                ranked.
              </p>
            ) : null}
          </Card>

          <Card className="border-dashed">
            <SectionTitle>Not built</SectionTitle>
            <ul className="flex list-disc flex-col gap-1 pl-4 text-xs text-slate-500">
              <li>
                Choosing which players to compare. The pair is fixed here until search can hand
                a selection to this screen.
              </li>
              <li>
                Metric direction is carried in the response. It should come from metric
                definitions in packages/shared so every screen agrees.
              </li>
              <li>
                Comparison is desktop only by design. Three columns of numbers do not survive a
                phone, and pretending otherwise makes a worse tool.
              </li>
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}

/**
 * The players' percentile radars on one chart (apps/api/app/services/radar.py). Each player is
 * placed among their own comparable players, and the card names each group, because two
 * players of different ages are not compared with the same population.
 */
function CompareRadar({ players }: { players: { id: string; name: string; sport: string }[] }) {
  const [radars, setRadars] = useState<(PlayerRadar | null)[] | null>(null);
  const key = players.map((p) => p.id).join(",");

  useEffect(() => {
    let alive = true;
    setRadars(null);
    Promise.all(players.map((p) => getRadar(p.id).catch(() => null))).then(
      (r) => alive && setRadars(r),
    );
    return () => {
      alive = false;
    };
    // `key` stands for the list of ids.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const sports = new Set(players.map((p) => p.sport));
  return (
    <Card>
      <SectionTitle>Match statistics, overlaid</SectionTitle>
      {sports.size > 1 ? (
        <p className="text-sm text-slate-500">
          These players play different sports, so their statistics cannot share a radar.
        </p>
      ) : !radars ? (
        <Skeleton className="h-64" />
      ) : (
        (() => {
          const usable = players
            .map((p, i) => ({ player: p, radar: radars[i], colour: RADAR_COLOURS[i] }))
            .filter((x) => x.radar && x.radar.axes.length > 0);
          if (usable.length < 2) {
            return (
              <p className="text-sm text-slate-500">
                Fewer than two of these players have enough match statistics on record for a
                radar.
              </p>
            );
          }
          // Axes every shown player has, in the order the first one lists them.
          const axes = usable[0].radar!.axes
            .filter((a) => usable.every((u) => u.radar!.axes.some((b) => b.key === a.key)))
            .map((a) => ({ key: a.key, label: a.label }));
          return (
            <div className="grid items-center gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <Radar
                axes={axes}
                series={usable.map((u) => ({
                  name: u.player.name,
                  values: Object.fromEntries(u.radar!.axes.map((a) => [a.key, a.percentile])),
                }))}
              />
              <ul className="flex flex-col gap-2 text-xs text-slate-400">
                {usable.map((u) => (
                  <li key={u.player.id} className="flex items-start gap-2">
                    <span
                      className="mt-1 inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                      style={{ background: u.colour }}
                      aria-hidden
                    />
                    <span>
                      <span className="font-semibold text-slate-200">{u.player.name}</span>, among{" "}
                      {u.radar!.population}.
                    </span>
                  </li>
                ))}
                <li className="text-slate-500">
                  Each player is placed among their own comparable players; higher is better on
                  every axis.
                </li>
              </ul>
            </div>
          );
        })()
      )}
    </Card>
  );
}
