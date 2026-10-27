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
import { useRouter, useSearchParams } from "next/navigation";
import { getComparison, getRadar, search } from "@/lib/api";
import { cx } from "@/lib/format";
import type { Comparison, PlayerRadar, SearchResult } from "@/lib/types";

/** The API compares two to four players (routers/comparison.py, MAX_PLAYERS). */
const MAX_PLAYERS = 4;

export default function ComparePage() {
  const [basis, setBasis] = useState<"age" | "maturity">("age");
  const [data, setData] = useState<Comparison | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Players come from the query string, which is what the player profile's Compare button
  // builds: /compare?players=<id>&players=<id>, or a single comma-separated value.
  const params = useSearchParams();
  const playerIds = useMemo(() => {
    const raw = params.getAll("players").flatMap((value) => value.split(","));
    return Array.from(new Set(raw.map((value) => value.trim()).filter(Boolean)));
  }, [params]);

  // Adding or removing a player rewrites the address, so a comparison can still be shared or
  // bookmarked, and the effect below loads it like any other.
  const router = useRouter();
  const setPlayers = (ids: string[]) =>
    router.replace(ids.length ? `/compare?players=${ids.map(encodeURIComponent).join(",")}` : "/compare");

  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);

    if (playerIds.length < 2) {
      setError(
        playerIds.length === 0
          ? "Add two to four players to compare: search for them below, or use Compare on a profile or in search."
          : "Comparison needs at least two players. Add another below.",
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
      <div className="flex flex-col gap-4">
        <h1 className="text-xl font-bold tracking-tight">Compare players</h1>
        <Card>
          <p className="text-sm text-slate-400">{error}</p>
        </Card>
        {playerIds.length > 0 ? (
          <Card className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="text-slate-400">
              {playerIds.length} player{playerIds.length === 1 ? "" : "s"} chosen so far.
            </span>
            <button className="text-xs text-slate-500 hover:text-slate-300" onClick={() => setPlayers([])}>
              Start over
            </button>
          </Card>
        ) : null}
        <PlayerPicker exclude={playerIds} onPick={(id) => setPlayers([...playerIds, id])} />
      </div>
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

          <div className="grid items-start gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data.players.map((entry) => (
              <Card key={entry.player.id} className="relative flex items-center gap-3">
                <button
                  className="absolute right-2 top-2 rounded px-1.5 text-sm text-slate-500 hover:bg-slate-800 hover:text-rose-300"
                  onClick={() => setPlayers(playerIds.filter((id) => id !== entry.player.id))}
                  aria-label={`Remove ${entry.player.fullName} from the comparison`}
                  title="Remove from the comparison"
                >
                  ×
                </button>
                <Avatar size={40} name={entry.player.fullName} />
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
            {data.players.length < MAX_PLAYERS ? (
              <PlayerPicker
                exclude={playerIds}
                onPick={(id) => setPlayers([...playerIds, id])}
                compact
              />
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

/**
 * Find a player by name and add them. Uses the same search as the Search screen, so it only
 * offers players the viewer may open; a withheld result is never offered.
 */
function PlayerPicker({
  exclude,
  onPick,
  compact = false,
}: {
  exclude: string[];
  onPick: (id: string) => void;
  compact?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<SearchResult[] | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setFound(null);
      return;
    }
    let alive = true;
    const timer = setTimeout(() => {
      search(q)
        .then((res) => alive && setFound(res.results.filter((r) => !r.withheld && !exclude.includes(r.player.id)).slice(0, 6)))
        .catch(() => alive && setFound([]));
    }, 300);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [query, exclude]);

  return (
    <Card className={cx("flex flex-col gap-2", compact && "border-dashed")}>
      <label className="text-xs uppercase tracking-[0.12em] text-slate-500" htmlFor="compare-add">
        Add a player
      </label>
      <input
        id="compare-add"
        dir="auto"
        className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none"
        placeholder="Type a name"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {found === null ? null : found.length === 0 ? (
        <p className="text-xs text-slate-500">No players you may open match that.</p>
      ) : (
        <ul className="flex flex-col">
          {found.map((r) => (
            <li key={r.player.id}>
              <button
                className="flex w-full items-baseline justify-between gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-slate-800"
                onClick={() => {
                  onPick(r.player.id);
                  setQuery("");
                }}
              >
                <span className="truncate text-slate-100" dir="auto">
                  {r.player.fullName}
                </span>
                <span className="shrink-0 text-xs text-slate-500">
                  {r.player.position ?? ""} {r.ageLabel}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
