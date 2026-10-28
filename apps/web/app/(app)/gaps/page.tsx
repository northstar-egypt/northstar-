"use client";

/**
 * Team gap analysis (decision 0003; apps/api/app/services/gaps.py, running ml/pro/gaps.py).
 *
 * Club mode: where a club ranks in its league on each team statistic, which of its bottom-third
 * ranks are stable enough to act on, and, for each, players from other clubs ranked on the
 * player statistics linked to it. National team mode: the federation names the needs, and every
 * Egypt-eligible player is ranked within their own league only.
 *
 * The rules are the analysis's: every percentile is shown, never a single fit score; a weakness
 * on a statistic that does not repeat from one half season to the next is shown and not acted
 * on; a player is ranked only with enough minutes, among enough players of their own league.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { Banner, Button, Card, Chip, Field, SectionTitle, Skeleton, Table, Td, Th, inputClass } from "@/components/ui";
import { getClubGaps, getGapOptions, getNationalGaps } from "@/lib/api";
import { cx, ordinal } from "@/lib/format";
import type { ClubGaps, GapCandidate, GapNeed, GapOptions } from "@/lib/types";

type Attribute = GapOptions["attributes"][number];

function formatValue(value: number | null, percent: boolean): string {
  if (value == null) return "n/a";
  return percent ? `${(value * 100).toFixed(1)}%` : value.toFixed(2);
}

function PercentileCell({ value }: { value: number | null }) {
  if (value == null) return <span className="text-slate-500">n/a</span>;
  return (
    <span
      className={cx(
        "tabular-nums font-semibold",
        value >= 70 ? "text-emerald-400" : value <= 30 ? "text-amber-400" : "text-slate-200",
      )}
    >
      {ordinal(value)}
    </span>
  );
}

function AttributeHeader({ attribute }: { attribute: Attribute | undefined }) {
  if (!attribute) return null;
  return (
    <span title={attribute.lowReliability ? "Repeats poorly from one half season to the next: weigh it less." : undefined}>
      {attribute.label}
      {attribute.lowReliability ? " *" : ""}
    </span>
  );
}

export default function GapsPage() {
  const [options, setOptions] = useState<GapOptions | null>(null);
  const [mode, setMode] = useState<"club" | "national">("club");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getGapOptions()
      .then(setOptions)
      .catch((e) => setError(e.message));
  }, []);

  const attributes = Object.fromEntries((options?.attributes ?? []).map((a) => [a.key, a]));

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Team gaps</h1>
        <p className="text-sm text-slate-400">
          Where a team is weak, and which players are strong exactly there.
        </p>
      </div>
      <div className="flex gap-2" role="tablist">
        <Button variant={mode === "club" ? "primary" : "default"} onClick={() => setMode("club")} role="tab" aria-selected={mode === "club"}>
          A club
        </Button>
        <Button variant={mode === "national" ? "primary" : "default"} onClick={() => setMode("national")} role="tab" aria-selected={mode === "national"}>
          The national team
        </Button>
      </div>
      {error ? <Banner tone="warn" title="Could not load">{error}</Banner> : null}
      {!options ? (
        error ? null : <Skeleton className="h-40" />
      ) : options.clubs.length === 0 ? (
        <Card>
          <p className="text-sm text-slate-500">No team seasons on record yet, so there is nothing to compare.</p>
        </Card>
      ) : mode === "club" ? (
        <ClubMode options={options} attributes={attributes} />
      ) : (
        <NationalMode options={options} attributes={attributes} />
      )}
      {options ? (
        <p className="text-xs text-slate-500">
          A player is ranked only with {options.minMinutes} minutes or more in the season, among at least{" "}
          {options.minCohort} players of the same position group in the same league and season. That minimum comes
          from checking how well each statistic from one half of a season agrees with the other half. Statistics
          marked * agree least, so weigh them less. A list is a starting point for a scout, not a recommendation.
        </p>
      ) : null}
    </div>
  );
}

function ClubMode({ options, attributes }: { options: GapOptions; attributes: Record<string, Attribute> }) {
  const [clubId, setClubId] = useState(options.clubs[0].id);
  const club = options.clubs.find((c) => c.id === clubId) ?? options.clubs[0];
  const [season, setSeason] = useState(club.seasons[0]);
  const [data, setData] = useState<ClubGaps | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    getClubGaps(clubId, season)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [clubId, season]);

  const weak = data?.profile.filter((m) => m.weak) ?? [];
  return (
    <div className="flex flex-col gap-5">
      <Card>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Club">
            <select
              className={inputClass}
              value={clubId}
              onChange={(e) => {
                const next = options.clubs.find((c) => c.id === e.target.value) ?? options.clubs[0];
                setClubId(next.id);
                setSeason(next.seasons[0]);
              }}
            >
              {options.clubs.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Season">
            <select className={inputClass} value={season} onChange={(e) => setSeason(e.target.value)}>
              {club.seasons.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </Card>
      {error ? <Banner tone="warn" title="Could not load">{error}</Banner> : null}
      {!data ? (
        error ? null : <Skeleton className="h-64" />
      ) : (
        <>
          <Card>
            <SectionTitle>
              {data.club.name}, {data.club.competition} {data.club.season}: against the league
            </SectionTitle>
            <Table>
              <thead>
                <tr>
                  <Th>Statistic</Th>
                  <Th className="text-right">Value</Th>
                  <Th className="text-right">Rank</Th>
                  <Th>Reading</Th>
                </tr>
              </thead>
              <tbody>
                {data.profile.map((m) => (
                  <tr key={m.key}>
                    <Td>
                      {m.label}
                      <span className="block text-xs text-slate-500">{m.better === "higher" ? "higher is better" : "lower is better"}</span>
                    </Td>
                    <Td className="text-right tabular-nums">
                      {m.value == null ? "n/a" : m.percent ? `${m.value.toFixed(1)}%` : m.value.toFixed(2)}
                    </Td>
                    <Td className="text-right tabular-nums">{m.rank == null ? "n/a" : `${ordinal(m.rank)} of ${m.of}`}</Td>
                    <Td>
                      {m.weak ? (
                        <Chip tone="warn">Weak spot</Chip>
                      ) : m.bottomUnstable ? (
                        <span className="text-xs text-slate-400">
                          Bottom third, but this barely repeats from one half season to the next, so it is not treated
                          as a weakness.
                        </span>
                      ) : null}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>

          {weak.length === 0 ? (
            <Card>
              <p className="text-sm text-slate-400">
                No weak spot: the club is not in the bottom third of the league on any statistic stable enough to act on.
              </p>
            </Card>
          ) : (
            weak.map((m) => (
              <Card key={m.key}>
                <SectionTitle>
                  {m.label}: {m.rank != null ? `${ordinal(m.rank)} of ${m.of}` : ""}
                </SectionTitle>
                {m.needs.length === 0 ? (
                  <p className="text-sm text-slate-500">{m.noPlayerLink ?? "No player statistic is linked to this."}</p>
                ) : (
                  <div className="flex flex-col gap-4">
                    {m.needs.map((need) => (
                      <NeedTable key={need.group} need={need} attributes={attributes} />
                    ))}
                  </div>
                )}
              </Card>
            ))
          )}

          <Card>
            <SectionTitle>The squad by position</SectionTitle>
            <p className="mb-3 text-xs text-slate-500">
              Who plays each group&apos;s minutes, and where they stand among the league&apos;s players of that group.
            </p>
            <div className="flex flex-col gap-5">
              {data.coverage.map((g) => (
                <div key={g.group}>
                  <p className="mb-1 text-sm font-semibold text-slate-200">
                    {g.label}{" "}
                    <span className="font-normal text-slate-500">(ranked among {g.population} in the league)</span>
                  </p>
                  {g.players.length === 0 ? (
                    <p className="text-sm text-slate-500">Nobody in this group played.</p>
                  ) : (
                    <Table>
                      <thead>
                        <tr>
                          <Th>Player</Th>
                          <Th className="text-right">Minutes</Th>
                          {g.attributes.map((a) => (
                            <Th key={a} className="text-right">
                              <AttributeHeader attribute={attributes[a]} />
                            </Th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {g.players.map((p) => (
                          <tr key={p.playerId}>
                            <Td>
                              <Link href={`/players/${p.playerId}`} className="text-sky-300 hover:underline">
                                {p.fullName}
                              </Link>
                            </Td>
                            <Td className="text-right tabular-nums">
                              {p.minutes}
                              <span className="block text-xs text-slate-500">{Math.round(p.share * 100)}% of the group</span>
                            </Td>
                            {g.attributes.map((a) => (
                              <Td key={a} className="text-right">
                                {p.ranked ? <PercentileCell value={p.percentiles[a]} /> : <span className="text-xs text-slate-500">too few minutes</span>}
                              </Td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  )}
                </div>
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

function NeedTable({ need, attributes }: { need: GapNeed; attributes: Record<string, Attribute> }) {
  return (
    <div>
      <p className="mb-1 text-sm font-semibold text-slate-200">{need.label}</p>
      {need.candidates.length === 0 ? (
        <p className="text-sm text-slate-500">No player of this group could be ranked.</p>
      ) : (
        <CandidateTable candidates={need.candidates} need={need} attributes={attributes} ranked />
      )}
      {need.unranked.length > 0 ? (
        <div className="mt-3">
          <p className="mb-1 text-xs text-slate-400">
            Not ranked: their league has too few players of this group on record to place them, so their numbers are
            shown as they are. Do not compare them with the percentiles above.
          </p>
          <CandidateTable candidates={need.unranked} need={need} attributes={attributes} ranked={false} />
        </div>
      ) : null}
    </div>
  );
}

function CandidateTable({
  candidates,
  need,
  attributes,
  ranked,
}: {
  candidates: GapCandidate[];
  need: GapNeed;
  attributes: Record<string, Attribute>;
  ranked: boolean;
}) {
  return (
    <Table>
      <thead>
        <tr>
          <Th>Player</Th>
          <Th>Club and league</Th>
          <Th className="text-right">Minutes</Th>
          {need.attributes.map((a) => (
            <Th key={a} className="text-right">
              <AttributeHeader attribute={attributes[a]} />
            </Th>
          ))}
          {ranked ? <Th className="text-right">Mean</Th> : null}
        </tr>
      </thead>
      <tbody>
        {candidates.map((c) => (
          <tr key={c.playerId}>
            <Td>
              <Link href={`/players/${c.playerId}`} className="text-sky-300 hover:underline">
                {c.fullName}
              </Link>
              {c.position ? <span className="block text-xs text-slate-500">{c.position}</span> : null}
            </Td>
            <Td>
              {c.club ?? "not known"}
              <span className="block text-xs text-slate-500">
                {c.competition} {c.season}
                {ranked ? `, among ${c.population}` : ""}
              </span>
            </Td>
            <Td className="text-right tabular-nums">{c.minutes}</Td>
            {need.attributes.map((a) => (
              <Td key={a} className="text-right">
                {ranked ? (
                  <PercentileCell value={c.percentiles[a]} />
                ) : (
                  <span className="tabular-nums text-slate-300">{formatValue(c.values[a], attributes[a]?.percent ?? false)}</span>
                )}
                {ranked ? (
                  <span className="block text-xs tabular-nums text-slate-500">
                    {formatValue(c.values[a], attributes[a]?.percent ?? false)}
                  </span>
                ) : null}
              </Td>
            ))}
            {ranked ? <Td className="text-right tabular-nums">{c.mean?.toFixed(0)}</Td> : null}
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function NationalMode({ options, attributes }: { options: GapOptions; attributes: Record<string, Attribute> }) {
  const [group, setGroup] = useState(options.groups[0].key);
  const [picked, setPicked] = useState<string[]>(options.groups[0].attributes.slice(0, 2));
  const [needs, setNeeds] = useState<string[]>([]);
  const [result, setResult] = useState<GapNeed[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const spec = options.groups.find((g) => g.key === group) ?? options.groups[0];

  async function find(list: string[]) {
    setBusy(true);
    setError(null);
    try {
      setResult((await getNationalGaps(list)).needs);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <SectionTitle>What the national team needs</SectionTitle>
        <p className="mb-3 text-sm text-slate-400">
          A national team plays too few matches for its own statistics to say where it is weak, so name the need: a
          position group and the statistics that matter. Every Egypt-eligible player with a league season is
          considered, at home and abroad, each ranked only among players of their own league.
        </p>
        <div className="grid gap-3 sm:grid-cols-[minmax(0,14rem)_1fr]">
          <Field label="Position group">
            <select
              className={inputClass}
              value={group}
              onChange={(e) => {
                const next = options.groups.find((g) => g.key === e.target.value) ?? options.groups[0];
                setGroup(next.key);
                setPicked(next.attributes.slice(0, 2));
              }}
            >
              {options.groups.map((g) => (
                <option key={g.key} value={g.key}>
                  {g.label}
                </option>
              ))}
            </select>
          </Field>
          <fieldset className="flex flex-col gap-1">
            <legend className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-400">Statistics</legend>
            <div className="flex flex-wrap gap-1.5">
              {spec.attributes.map((a) => (
                <Chip
                  key={a}
                  active={picked.includes(a)}
                  onClick={() => setPicked((now) => (now.includes(a) ? now.filter((x) => x !== a) : [...now, a]))}
                >
                  {attributes[a]?.label ?? a}
                  {attributes[a]?.lowReliability ? " *" : ""}
                </Chip>
              ))}
            </div>
          </fieldset>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            disabled={picked.length === 0 || needs.length >= 6}
            onClick={() => {
              const next = [...needs.filter((n) => !n.startsWith(`${group}:`)), `${group}:${picked.join(",")}`];
              setNeeds(next);
              void find(next);
            }}
          >
            Add this need
          </Button>
          {needs.map((n) => {
            const [g, list] = n.split(":");
            const label = options.groups.find((x) => x.key === g)?.label ?? g;
            return (
              <Chip
                key={n}
                onClick={() => {
                  const next = needs.filter((x) => x !== n);
                  setNeeds(next);
                  if (next.length) void find(next);
                  else setResult(null);
                }}
                title="Remove this need"
              >
                {label}: {list.split(",").map((a) => attributes[a]?.label ?? a).join(", ")} &times;
              </Chip>
            );
          })}
        </div>
      </Card>
      {error ? <Banner tone="warn" title="Could not load">{error}</Banner> : null}
      {busy ? <Skeleton className="h-40" /> : null}
      {!busy && result
        ? result.map((need) => (
            <Card key={`${need.group}-${need.attributes.join()}`}>
              <NeedTable need={need} attributes={attributes} />
            </Card>
          ))
        : null}
    </div>
  );
}
