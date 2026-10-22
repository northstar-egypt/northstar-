"use client";

/**
 * The explorer: every comparable player on two statistics at once, or a group's leaders.
 *
 * A scout rarely asks "how good is this one player". They ask who stands out on two things
 * together: shoots a lot and scores, passes a lot and completes them. This screen answers that
 * for any two of the statistics on the profile's radar. The Leaders tab answers the question
 * before it: with the same filters, the best players on each statistic, each with a percentile
 * among the whole group.
 *
 * Everything decided here is decided by the API (apps/api/app/services/explore.py): who is in
 * the group, who may be drawn, and whether there are enough players for median lines. The
 * screen draws what it is sent and repeats the API's note, so it never implies more than is
 * known. Opened from a profile (?focus=<id>), it takes that player's sport, gender and position
 * group and marks them.
 */

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { ScatterPlot } from "@/components/charts";
import { Card, Field, SectionTitle, Skeleton, Td, Th, inputClass } from "@/components/ui";
import { getLeaders, getScatter } from "@/lib/api";
import { cx, ordinal } from "@/lib/format";
import type { Leaders, Scatter, ScatterQuery } from "@/lib/types";

const SPORTS = [
  { value: "football", label: "Football" },
  { value: "table_tennis", label: "Table tennis" },
];
const GROUP_LABELS: Record<string, string> = {
  goalkeeper: "Goalkeepers",
  defender: "Defenders",
  midfielder: "Midfielders",
  forward: "Forwards",
};
const LIST_LENGTH = 15;

export default function ExplorePage() {
  const params = useSearchParams();
  // A link can set any filter (the assistant's "Open in Explore" does); unset ones are left to
  // the API's defaults.
  const [query, setQuery] = useState<ScatterQuery>(() => {
    const age = (key: string) => (params.get(key) === null ? undefined : Number(params.get(key)));
    return {
      focus: params.get("focus") ?? undefined,
      sport: params.get("sport") ?? undefined,
      gender: params.get("gender") ?? undefined,
      group: params.get("group") ?? undefined,
      ageFrom: age("ageFrom"),
      ageTo: age("ageTo"),
      x: params.get("x") ?? undefined,
      y: params.get("y") ?? undefined,
    };
  });
  const [data, setData] = useState<Scatter | null>(null);
  const [view, setView] = useState<"plot" | "leaders">(() =>
    params.get("view") === "leaders" ? "leaders" : "plot",
  );
  const [leaders, setLeaders] = useState<Leaders | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [showAll, setShowAll] = useState(false);
  // A phone gets a squarer, smaller drawing, so its axis text stays readable when scaled.
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 640px)");
    const update = () => setNarrow(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    let alive = true;
    setError(null);
    getScatter(query)
      .then((s) => alive && setData(s))
      .catch((err) => alive && setError(err.message));
    return () => {
      alive = false;
    };
  }, [query]);

  // The leaders follow the filters the plot's response echoed, so both tabs always describe
  // the same group.
  useEffect(() => {
    if (view !== "leaders" || !data) return;
    let alive = true;
    setLeaders(null);
    getLeaders({
      sport: data.sport,
      gender: data.gender,
      group: data.group ?? "all",
      ageFrom: data.ageFrom ?? undefined,
      ageTo: data.ageTo ?? undefined,
      focus: data.focus ?? undefined,
      ownAge: false,
    })
      .then((l) => alive && setLeaders(l))
      .catch((err) => alive && setError(err.message));
    return () => {
      alive = false;
    };
  }, [view, data]);

  // Every control sends the filters the API last echoed, plus the one change, so a focus
  // player's sport and group stay put when only a statistic is changed.
  const change = (patch: ScatterQuery) => {
    setShowAll(false);
    setQuery({
      sport: data?.sport,
      gender: data?.gender,
      group: data?.group ?? "all",
      ageFrom: data?.ageFrom ?? undefined,
      ageTo: data?.ageTo ?? undefined,
      x: data?.x,
      y: data?.y,
      focus: data?.focus ?? undefined,
      // The first view of a player's link opens on their own ages; from here the viewer's
      // filters are what count, including clearing the ages to "any".
      ownAge: false,
      ...patch,
    });
  };

  const marked = useMemo(() => {
    const ids = new Set<string>();
    if (data?.focus) ids.add(data.focus);
    const wanted = name.trim().toLowerCase();
    if (data && wanted.length >= 2) {
      for (const p of data.points) if (p.fullName.toLowerCase().includes(wanted)) ids.add(p.playerId);
    }
    return ids;
  }, [data, name]);

  const stat = (key: string) => data?.stats.find((s) => s.key === key);
  const axisLabel = (key: string) => {
    const s = stat(key);
    return s ? `${s.label} (${s.unit})${s.higherIsBetter ? "" : ", lower is better"}` : key;
  };
  const listed = useMemo(() => {
    if (!data) return [];
    const better = stat(data.y)?.higherIsBetter ?? true;
    return [...data.points].sort((a, b) => (better ? b.y - a.y : a.y - b.y));
  }, [data]);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Explore players</h1>
          <p className="text-sm text-slate-400">
            {view === "plot"
              ? "Comparable players on any two match statistics. Each point opens that player's profile."
              : "The best players on each match statistic, among the group you pick."}
          </p>
        </div>
        <div className="flex rounded-md border border-slate-700 p-0.5" role="tablist">
          {(["plot", "leaders"] as const).map((v) => (
            <button
              key={v}
              role="tab"
              aria-selected={view === v}
              onClick={() => setView(v)}
              className={cx(
                "rounded px-3 py-1 text-sm",
                view === v ? "bg-slate-800 text-slate-100" : "text-slate-400 hover:text-slate-200",
              )}
            >
              {v === "plot" ? "Plot" : "Leaders"}
            </button>
          ))}
        </div>
      </div>

      <Card>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
          <Field label="Sport">
            <select
              className={inputClass}
              value={data?.sport ?? query.sport ?? "football"}
              onChange={(e) => {
                setShowAll(false);
                setQuery({ sport: e.target.value });
              }}
            >
              {SPORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Gender">
            <select
              className={inputClass}
              value={data?.gender ?? ""}
              disabled={!data || data.genders.length < 2}
              onChange={(e) => change({ gender: e.target.value, focus: undefined })}
            >
              {(data?.genders ?? []).map((g) => (
                <option key={g} value={g}>
                  {g === "male" ? "Men and boys" : "Women and girls"}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Position">
            <select
              className={inputClass}
              value={data?.group ?? "all"}
              disabled={!data || data.groups.length === 0}
              onChange={(e) => change({ group: e.target.value, x: undefined, y: undefined })}
            >
              <option value="all">Every position</option>
              {(data?.groups ?? []).map((g) => (
                <option key={g} value={g}>
                  {GROUP_LABELS[g] ?? g}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Age from">
            <input
              className={inputClass}
              type="number"
              min={0}
              max={60}
              placeholder="any"
              defaultValue={data?.ageFrom ?? ""}
              key={`from-${data?.ageFrom ?? ""}`}
              onBlur={(e) => change({ ageFrom: e.target.value === "" ? undefined : Number(e.target.value) })}
            />
          </Field>
          <Field label="Age to">
            <input
              className={inputClass}
              type="number"
              min={0}
              max={60}
              placeholder="any"
              defaultValue={data?.ageTo ?? ""}
              key={`to-${data?.ageTo ?? ""}`}
              onBlur={(e) => change({ ageTo: e.target.value === "" ? undefined : Number(e.target.value) })}
            />
          </Field>
          {view === "plot" ? (
          <>
          <Field label="Across">
            <select className={inputClass} value={data?.x ?? ""} onChange={(e) => change({ x: e.target.value })}>
              {(data?.stats ?? []).map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Up">
            <select className={inputClass} value={data?.y ?? ""} onChange={(e) => change({ y: e.target.value })}>
              {(data?.stats ?? []).map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>
          </>
          ) : null}
        </div>
      </Card>

      {error ? (
        <Card>
          <p className="text-sm text-amber-300">{error}</p>
        </Card>
      ) : !data ? (
        <Skeleton className="h-96" />
      ) : view === "leaders" ? (
        leaders ? <LeaderBoards leaders={leaders} /> : <Skeleton className="h-96" />
      ) : (
        <>
          <Card>
            <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
              <p className="text-sm text-slate-300">
                {data.points.length} shown of {data.population}.
              </p>
              <div className="w-full sm:w-64">
                <Field label="Mark a player by name">
                  <input
                    className={inputClass}
                    value={name}
                    placeholder="Type part of a name"
                    onChange={(e) => setName(e.target.value)}
                  />
                </Field>
              </div>
            </div>
            {data.points.length === 0 ? (
              <p className="text-sm text-slate-500">No players here you may open.</p>
            ) : (
              <ScatterPlot
                dots={data.points.map((p) => ({
                  id: p.playerId,
                  name: p.fullName,
                  x: p.x,
                  y: p.y,
                  href: `/players/${p.playerId}`,
                }))}
                xLabel={axisLabel(data.x)}
                yLabel={axisLabel(data.y)}
                medians={data.medians}
                marked={marked}
                width={narrow ? 380 : 640}
                height={narrow ? 380 : 420}
              />
            )}
            <p className="mt-2 text-xs text-slate-500">{data.note}</p>
          </Card>

          {listed.length > 0 ? (
            <Card>
              <SectionTitle>Players by {stat(data.y)?.label.toLowerCase() ?? data.y}</SectionTitle>
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr>
                    <Th>Player</Th>
                    <Th className="hidden sm:table-cell">Position</Th>
                    <Th className="hidden sm:table-cell">Age</Th>
                    <Th className="text-right">{stat(data.x)?.label ?? data.x}</Th>
                    <Th className="text-right">{stat(data.y)?.label ?? data.y}</Th>
                  </tr>
                </thead>
                <tbody>
                  {(showAll ? listed : listed.slice(0, LIST_LENGTH)).map((p) => (
                    <tr key={p.playerId} className={marked.has(p.playerId) ? "bg-amber-500/10" : undefined}>
                      <Td>
                        <Link href={`/players/${p.playerId}`} className="text-sky-300 hover:underline">
                          {p.fullName}
                        </Link>
                      </Td>
                      <Td className="hidden sm:table-cell">{p.position ?? "n/a"}</Td>
                      <Td className="hidden sm:table-cell">{p.ageLabel}</Td>
                      <Td className="text-right tabular-nums">{p.x}</Td>
                      <Td className="text-right tabular-nums">{p.y}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {listed.length > LIST_LENGTH && !showAll ? (
                <button className="mt-3 text-sm text-sky-300 hover:underline" onClick={() => setShowAll(true)}>
                  Show all {listed.length}
                </button>
              ) : null}
            </Card>
          ) : null}
        </>
      )}
    </div>
  );
}

/** One card per statistic: its median, its leaders, and where the focus player stands. */
function LeaderBoards({ leaders }: { leaders: Leaders }) {
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <p className="text-sm text-slate-300">
          {leaders.shown} you may open, of {leaders.population}.
        </p>
        <p className="mt-1 text-xs text-slate-500">{leaders.note}</p>
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        {leaders.boards.map((b) => {
          const focusListed = b.focus && b.leaders.some((l) => l.playerId === b.focus?.playerId);
          return (
            <Card key={b.key}>
              <SectionTitle>
                {b.label} ({b.unit}){b.higherIsBetter ? "" : ", lower is better"}
              </SectionTitle>
              {b.median == null ? (
                <p className="text-sm text-slate-500">
                  No leaders: too few players have this on record, or they all have the same value.
                </p>
              ) : (
                <>
                  <p className="mb-2 text-xs text-slate-500">
                    Median {b.median} among {b.comparedWith} players.
                  </p>
                  {b.leaders.length === 0 ? (
                    <p className="text-sm text-slate-500">None of them are players you may open.</p>
                  ) : (
                    <ol className="flex flex-col gap-1 text-sm">
                      {b.leaders.map((l, i) => (
                        <li
                          key={l.playerId}
                          className={cx(
                            "flex items-baseline justify-between gap-3 rounded px-1",
                            l.playerId === leaders.focus && "bg-amber-500/10",
                          )}
                        >
                          <span className="min-w-0 truncate">
                            <span className="mr-2 inline-block w-4 text-slate-500">{i + 1}</span>
                            <Link href={`/players/${l.playerId}`} className="text-sky-300 hover:underline">
                              {l.fullName}
                            </Link>
                            <span className="ml-2 text-xs text-slate-500">
                              {l.position ? `${l.position}, ` : ""}
                              {l.ageLabel}
                            </span>
                          </span>
                          <span className="shrink-0 tabular-nums text-slate-400">
                            {l.value}
                            <span className="ml-2 inline-block w-12 text-right font-semibold text-slate-100">
                              {ordinal(l.percentile)}
                            </span>
                          </span>
                        </li>
                      ))}
                    </ol>
                  )}
                  {b.focus && !focusListed ? (
                    <p className="mt-2 rounded bg-amber-500/10 px-1 text-sm text-slate-300">
                      {b.focus.fullName} is {ordinal(b.focus.rank ?? 0)} of the players you may open:{" "}
                      {b.focus.value}, {ordinal(b.focus.percentile)} percentile.
                    </p>
                  ) : null}
                </>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}
