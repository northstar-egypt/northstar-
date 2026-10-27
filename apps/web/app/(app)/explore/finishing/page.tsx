"use client";

/**
 * Rates read from tagged match events (decision 0007): football's finishing, how often shots
 * become goals, by where in the goal, technique, situation and the keeper's distance; table
 * tennis's points won, by stroke. Which analyses exist, and their details, come from the sport
 * modules, so this screen knows no sport.
 *
 * The rules are the platform's: only players with analytics consent are counted, a player is
 * named only to a caller who may open them, no rate is shown from fewer attempts than the API
 * says (its counts are), and the screen says how many tags were made by the synthetic data
 * generator, whose rates show how it was written rather than how anyone finishes.
 */

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { GoalMouth } from "@/components/charts";
import { Banner, Card, Field, Label, SectionTitle, Skeleton, Table, Td, Th, inputClass } from "@/components/ui";
import { getEventAnalysis, getSports } from "@/lib/api";
import type { EventAnalysis, SportModule } from "@/lib/types";

const GROUP_WORDS: Record<string, string> = {
  goalkeeper: "Goalkeepers",
  defender: "Defenders",
  midfielder: "Midfielders",
  forward: "Forwards",
};

function pct(rate: number | null): string {
  return rate == null ? "" : `${Math.round(rate * 100)}%`;
}

export default function FinishingPage() {
  const params = useSearchParams();
  const router = useRouter();
  const [modules, setModules] = useState<SportModule[]>([]);
  const sport = params.get("sport") ?? "football";
  const sportModule = modules.find((m) => m.sport === sport);
  const key = params.get("key") ?? sportModule?.analyses?.[0]?.key ?? null;
  const [data, setData] = useState<EventAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSports()
      .then((all) => setModules(all.filter((m) => (m.analyses ?? []).length > 0)))
      .catch((e) => setError(e.message));
  }, []);

  // The address holds the question, so a view can be shared and the back button works.
  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params.toString());
    for (const [name, value] of Object.entries(changes)) {
      if (value) next.set(name, value);
      else next.delete(name);
    }
    router.replace(`/explore/finishing?${next.toString()}`);
  };

  useEffect(() => {
    if (!key) return;
    let alive = true;
    setData(null);
    setError(null);
    getEventAnalysis(sport, key, {
      gender: params.get("gender"),
      group: params.get("group"),
      ageFrom: params.get("ageFrom") ? Number(params.get("ageFrom")) : null,
      ageTo: params.get("ageTo") ? Number(params.get("ageTo")) : null,
      player: params.get("player"),
    })
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [sport, key, params]);

  const analysis = sportModule?.analyses?.find((a) => a.key === key);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">{analysis?.label ?? "Tagged events"}</h1>
          <p className="text-sm text-slate-400">
            Read from the events coaches tag from match video: how often an attempt{" "}
            {analysis ? `${analysis.rateLabel}` : "succeeded"}, by what they recorded about it.
          </p>
        </div>
        <Link href="/explore" className="text-sm text-sky-300 hover:underline">
          Back to Explore
        </Link>
      </div>

      <Card>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <Field label="Sport">
            <select
              className={inputClass}
              value={sport}
              onChange={(e) => set({ sport: e.target.value, key: null, gender: null, group: null, player: null })}
            >
              {modules.map((m) => (
                <option key={m.sport} value={m.sport}>
                  {m.label}
                </option>
              ))}
            </select>
          </Field>
          {data && data.genders.length > 1 ? (
            <Field label="Gender">
              <select className={inputClass} value={data.gender} onChange={(e) => set({ gender: e.target.value })}>
                {data.genders.map((g) => (
                  <option key={g} value={g}>
                    {g === "female" ? "Women and girls" : "Men and boys"}
                  </option>
                ))}
              </select>
            </Field>
          ) : null}
          {data && data.groups.length ? (
            <Field label="Position">
              <select className={inputClass} value={data.group ?? ""} onChange={(e) => set({ group: e.target.value || null })}>
                <option value="">Every position</option>
                {data.groups.map((g) => (
                  <option key={g} value={g}>
                    {GROUP_WORDS[g] ?? g}
                  </option>
                ))}
              </select>
            </Field>
          ) : null}
          <Field label="Age from">
            <input
              className={inputClass}
              type="number"
              min={5}
              max={60}
              placeholder="any"
              defaultValue={params.get("ageFrom") ?? ""}
              onBlur={(e) => set({ ageFrom: e.target.value || null })}
            />
          </Field>
          <Field label="Age to">
            <input
              className={inputClass}
              type="number"
              min={5}
              max={60}
              placeholder="any"
              defaultValue={params.get("ageTo") ?? ""}
              onBlur={(e) => set({ ageTo: e.target.value || null })}
            />
          </Field>
        </div>
      </Card>

      {error ? <Banner tone="warn">{error}</Banner> : null}
      {!data && !error ? <Skeleton className="h-64" /> : null}

      {data ? (
        <>
          {data.generated > 0 ? (
            <Banner tone="warn" title="Generated data">
              {data.note}
            </Banner>
          ) : (
            <p className="text-xs text-slate-500">{data.note}</p>
          )}

          <Card>
            <p className="text-sm text-slate-300">{data.population.charAt(0).toUpperCase() + data.population.slice(1)}.</p>
            <p className="mt-1 text-2xl font-bold tabular-nums">
              {data.successes} of {data.attempts} {data.rateLabel}
              {data.rate != null ? <span className="ml-2 text-slate-400">{pct(data.rate)}</span> : null}
            </p>
            {data.player ? (
              <p className="mt-2 text-sm text-slate-300" dir="auto">
                {data.player.fullName}: {data.player.successes} of {data.player.attempts} {data.rateLabel}
                {data.player.rate != null
                  ? `, ${pct(data.player.rate)}`
                  : `; a rate needs ${data.minAttempts} attempts`}
                {data.player.percentile != null
                  ? `, ${data.player.percentile}th percentile of the ${data.qualifying} players with ${data.minAttempts} or more`
                  : ""}
                .
              </p>
            ) : null}
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            {data.breakdown.map((b) => {
              const best = Math.max(0.0001, ...b.values.map((v) => v.rate ?? 0));
              return (
                <Card key={b.key}>
                  <SectionTitle>{b.label}</SectionTitle>
                  <p className="mb-3 text-xs text-slate-500">
                    Recorded on {b.recorded} of {data.attempts}
                    {b.among ? ` (only on ${b.among})` : ""}. No rate from fewer than {data.minForARate}.
                  </p>
                  {b.grid ? (
                    <GoalMouth
                      grid={b.grid}
                      cells={b.values.map((v) => ({
                        key: v.key,
                        label: v.label,
                        value: v.rate != null ? pct(v.rate) : undefined,
                        sub: `${v.successes} of ${v.attempts}`,
                        fill: v.rate != null ? v.rate / best : 0,
                      }))}
                    />
                  ) : (
                    <ul className="flex flex-col gap-2">
                      {b.values.map((v) => (
                        <li key={v.key} className="flex flex-col gap-1">
                          <div className="flex items-baseline justify-between gap-2 text-sm">
                            <span>{v.label}</span>
                            <span className="tabular-nums text-slate-400">
                              {v.successes} of {v.attempts}
                              <span className="ml-2 w-10 font-semibold text-slate-200">{pct(v.rate) || "–"}</span>
                            </span>
                          </div>
                          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800" aria-hidden>
                            <div className="h-full bg-sky-500/80" style={{ width: `${v.rate != null ? (v.rate / best) * 100 : 0}%` }} />
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              );
            })}
          </div>

          <Card>
            <SectionTitle>Best rates, {data.minAttempts} attempts or more</SectionTitle>
            {data.leaders.length === 0 ? (
              <p className="text-sm text-slate-500">
                {data.qualifying === 0
                  ? `Nobody here has ${data.minAttempts} attempts tagged yet.`
                  : "None of the players with enough attempts are players you may open."}
              </p>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Player</Th>
                    <Th>Position</Th>
                    <Th>Age</Th>
                    <Th className="text-right">Attempts</Th>
                    <Th className="text-right">{data.rateLabel.charAt(0).toUpperCase() + data.rateLabel.slice(1)}</Th>
                    <Th className="text-right">Rate</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.leaders.map((l) => (
                    <tr key={l.playerId}>
                      <Td>
                        <Link href={`/players/${l.playerId}`} className="text-sky-300 hover:underline" dir="auto">
                          {l.fullName}
                        </Link>
                      </Td>
                      <Td>{l.position ?? ""}</Td>
                      <Td>{l.ageLabel}</Td>
                      <Td className="text-right tabular-nums">{l.attempts}</Td>
                      <Td className="text-right tabular-nums">{l.successes}</Td>
                      <Td className="text-right font-semibold tabular-nums">{pct(l.rate)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
            <Label>
              <span className="mt-2 block normal-case tracking-normal text-slate-500">
                {data.qualifying} players have {data.minAttempts} or more; only those you may open are named.
              </span>
            </Label>
          </Card>
        </>
      ) : null}
    </div>
  );
}
