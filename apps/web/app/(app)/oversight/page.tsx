"use client";

/**
 * The federation's home. See docs/wireframes/07-federation-oversight.html.
 *
 * The national view. It opens on what needs a decision today (the integrity queue, the academies
 * to call, the national team's needs), then who stepped up, then whether the country's talent data
 * is any good: who is covered, who is missing, and which academies are actually keeping records.
 *
 * Two deliberate choices. Staleness is the headline rather than player count, because a
 * federation can grow the count by onboarding one large academy and learn nothing. And coverage
 * is shown per million people rather than as a raw total, because Cairo will always have the
 * most tracked players and the interesting fact is the governorate with five million people and
 * eleven of them.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { RatioBars, StackedAges } from "@/components/charts";
import {
  Button,
  Card,
  Chip,
  SectionTitle,
  Skeleton,
  Stat,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { getFlags, getOversight, getScoutHome, getStrongestRated } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { STALE_DAYS, cx } from "@/lib/format";
import { ROLE_IDENTITY } from "@/lib/roles";
import type { IntegrityFlag, OversightSummary, ScoutHome, StrongestGroup } from "@/lib/types";

const SPORTS = [
  { key: "football", label: "football" },
  { key: "table_tennis", label: "table tennis" },
];
const FLAG_WORDS: Record<string, string> = { fraud: "Possible fraud", duplicate: "Possible duplicate", anomaly: "Anomaly" };
const pct = (x: number) => `${Math.round(x * 100)}%`;

export default function OversightPage() {
  const { user } = useAuth();
  const identity = ROLE_IDENTITY[user?.role ?? "federation"];
  const [sport, setSport] = useState("football");
  const [data, setData] = useState<OversightSummary | null>(null);
  // Each of these has its own endpoint and can fail alone: the rest of the home still stands.
  const [flags, setFlags] = useState<IntegrityFlag[] | null>(null);
  const [talent, setTalent] = useState<ScoutHome | null>(null);
  const [strongest, setStrongest] = useState<StrongestGroup[] | null>(null);

  useEffect(() => {
    let alive = true;
    setData(null);
    getOversight(sport).then((d) => alive && setData(d));
    return () => {
      alive = false;
    };
  }, [sport]);

  useEffect(() => {
    let alive = true;
    getFlags().then((f) => alive && setFlags(f)).catch(() => alive && setFlags(null));
    getScoutHome().then((h) => alive && setTalent(h)).catch(() => alive && setTalent(null));
    getStrongestRated().then((g) => alive && setStrongest(g)).catch(() => alive && setStrongest(null));
    return () => {
      alive = false;
    };
  }, []);

  if (!data) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24" />
        <Skeleton className="h-56" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  const academies = [...data.academies].sort(
    (a, b) => (b.medianStalenessDays ?? -1) - (a.medianStalenessDays ?? -1),
  );
  // Governorate code to name, from the same response.
  const regionName = Object.fromEntries(data.byRegion.map((r) => [r.code, r.region]));
  const youthAcademies = academies.filter((a) => a.youthPlayers > 0);
  const toCall = youthAcademies
    .filter((a) => (a.lastSubmissionDays ?? 0) >= STALE_DAYS || a.consentCompletePct < 70)
    .slice(0, 3);
  const noCoverage = data.byRegion.every((r) => r.players === 0);
  const football = sport === "football";

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className={cx("text-3xl font-bold tracking-tight", identity.text)}>
            {identity.greeting(user?.fullName?.split(" ")[0] ?? null)}
          </h1>
          <p className="mt-1 text-slate-400">{identity.tagline}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {SPORTS.map((s) => (
            <Chip key={s.key} tone={sport === s.key ? "brand" : "default"} active={sport === s.key} onClick={() => setSport(s.key)}>
              {s.label}
            </Chip>
          ))}
          <Link href="/results/import">
            <Button variant="ghost">Import table tennis results</Button>
          </Link>
        </div>
      </div>

      {/* What needs a person today comes first. */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className={cx("border-l-4", identity.border)}>
          <h2 className="text-lg font-semibold">Integrity queue</h2>
          <p className="mb-2 text-sm text-slate-400">
            {flags == null ? "Could not load the queue." : `${flags.length} open, across every sport`}
          </p>
          <ul className="mb-3 flex flex-col gap-1.5 text-sm">
            {(flags ?? []).slice(0, 3).map((f) => (
              <li key={f.id} className="flex items-baseline justify-between gap-2">
                <span className="min-w-0 truncate text-slate-200">{f.playerName}</span>
                <span className="shrink-0 text-xs text-slate-500">
                  {FLAG_WORDS[f.type] ?? f.type}, {f.ageDays} days
                </span>
              </li>
            ))}
          </ul>
          <Link href="/integrity">
            <Button size="sm">Review the board</Button>
          </Link>
        </Card>

        <Card className={cx("border-l-4", identity.border)}>
          <h2 className="text-lg font-semibold">Who needs a call</h2>
          {youthAcademies.length === 0 ? (
            <p className="text-sm text-slate-400">
              No {SPORTS.find((s) => s.key === sport)?.label} clubs or academies with young players on record.
            </p>
          ) : toCall.length === 0 ? (
            <p className="text-sm text-slate-400">
              Every academy has measured a young player in the last {STALE_DAYS} days, with consent mostly complete.
            </p>
          ) : (
            <>
              <p className="mb-2 text-sm text-slate-400">Records gone quiet, or consent incomplete</p>
              <ul className="flex flex-col gap-1.5 text-sm">
                {toCall.map((a) => (
                  <li key={a.organization.id} className="flex items-baseline justify-between gap-2">
                    <span className="min-w-0 truncate text-slate-200">{a.organization.name}</span>
                    <span className="shrink-0 text-xs text-slate-500">
                      {a.lastSubmissionDays ?? "no"} days, {a.consentCompletePct}% consent
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>

        {football ? (
          <Card className={cx("border-l-4", identity.border)}>
            <h2 className="text-lg font-semibold">The national team</h2>
            <p className="mb-3 text-sm text-slate-400">
              Name a need, and see Egypt-eligible players at home and abroad, each ranked within their own league.
            </p>
            <div className="mb-3 flex flex-wrap gap-1.5">
              <Chip tone="brand">{data.diaspora.total} Egypt eligible abroad</Chip>
              <Chip>{data.diaspora.under21} under 21</Chip>
              {/* Equal to the total only when everyone arrived at once, which is an import, not news. */}
              {data.diaspora.newThisMonth > 0 && data.diaspora.newThisMonth < data.diaspora.total ? (
                <Chip tone="good">{data.diaspora.newThisMonth} new this month</Chip>
              ) : null}
            </div>
            <Link href="/gaps">
              <Button size="sm">Open team gaps</Button>
            </Link>
          </Card>
        ) : (
          <Card className={cx("border-l-4", identity.border)}>
            <h2 className="text-lg font-semibold">Results</h2>
            <p className="mb-3 text-sm text-slate-400">
              Ratings only count confirmed matches. A results file counts directly; a result a player submits counts
              once it is confirmed.
            </p>
            <Link href="/results/import">
              <Button size="sm">Import results</Button>
            </Link>
          </Card>
        )}
      </div>

      {football && talent && talent.breakouts.length > 0 ? (
        <Card>
          <SectionTitle
            action={
              <Link href="/gaps" className="text-xs text-sky-300 hover:underline">
                Compare with what teams need
              </Link>
            }
          >
            Stepped up in {talent.breakoutSeason}
          </SectionTitle>
          <ul className="grid gap-x-8 gap-y-2 md:grid-cols-2">
            {talent.breakouts.slice(0, 6).map((b) => (
              <li key={b.playerId} className="min-w-0">
                <Link href={`/players/${b.playerId}`} className="font-semibold text-slate-100 hover:underline">
                  {b.fullName}
                </Link>
                <span className="ml-2 text-xs text-slate-500">
                  {[b.position, b.ageLabel, b.club].filter(Boolean).join(" · ")}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-slate-500">
            Players aged 18 to 23 whose share of their team&apos;s chances clearly rose on the season before. A claim to
            check, not a verdict.
          </p>
        </Card>
      ) : null}

      {!football ? (
        <Card>
          <SectionTitle>Strongest rated players</SectionTitle>
          {!strongest || strongest.length === 0 ? (
            <p className="text-sm text-slate-400">
              No ratings to show yet: a rating appears once a player has enough confirmed matches.
            </p>
          ) : (
            <div className="grid gap-5 md:grid-cols-2">
              {strongest.map((group) => (
                <div key={group.gender}>
                  <p className="mb-2 text-sm font-semibold text-slate-200 first-letter:uppercase">
                    {group.population.replace("registered ", "").replace(" in table tennis", "")}
                  </p>
                  <ul className="flex flex-col gap-1.5 text-sm">
                    {group.players.map((p) => (
                      <li key={p.playerId} className="flex items-baseline justify-between gap-3">
                        <Link href={`/players/${p.playerId}`} className="min-w-0 truncate text-slate-200 hover:underline">
                          {p.fullName}
                        </Link>
                        <span className="shrink-0 text-xs tabular-nums text-slate-400">
                          <span className="font-semibold text-slate-100">{pct(p.pointShare)}</span> ({pct(p.low)} to {pct(p.high)}),{" "}
                          {p.ratedMatches} matches
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
          <p className="mt-3 text-xs text-slate-500">
            Share of points against an average opponent of the same gender, with its range. Players are only compared
            within one gender.
          </p>
        </Card>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Players tracked" value={data.playersTracked.toLocaleString("en-GB")} />
        <Stat label="Academies reporting" value={data.academiesReporting} />
        <Stat
          label={`Young players not measured in ${STALE_DAYS} days`}
          value={`${data.stalePct}%`}
          tone={data.stalePct > 15 ? "warn" : "good"}
          hint="the number that says whether any of this is trustworthy"
        />
        <Stat label="Open flags" value={data.openFlags} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionTitle>Coverage by governorate</SectionTitle>
          {noCoverage ? (
            <p className="text-sm text-slate-400">
              No {SPORTS.find((s) => s.key === sport)?.label} players are at a club with a governorate on record, so there
              is no coverage to show. Players here register themselves or come from results files.
            </p>
          ) : (
          <>
          <RatioBars
            rows={data.byRegion.map((r) => ({
              label: r.region,
              value: r.players,
              per: r.populationM,
            }))}
          />
          <p className="mt-3 text-xs text-slate-500">
            Players tracked per million people, by where their club is: all 27 governorates, so
            the ones the platform has not reached show as the gaps they are (
            {data.byRegion.filter((r) => r.players === 0).length} with no tracked players). Amber
            marks thin coverage, and &ldquo;none&rdquo; a governorate with no tracked players at all. Populations are 2023 estimates.
            {data.playersWithoutGovernorate > 0
              ? ` ${data.playersWithoutGovernorate} players are at clubs with no governorate set and are not counted here.`
              : ""}
          </p>
          </>
          )}
        </Card>

        <Card>
          <SectionTitle>{football ? "Players by age and tier" : "Players by age"}</SectionTitle>
          <StackedAges rows={data.byAgeTier} />
          <p className="mt-3 text-xs text-slate-500">
            {firstPro(data.byAgeTier) !== null
              ? `The professional tier begins at ${firstPro(data.byAgeTier)} here, which is expected. `
              : ""}
            {football
              ? "A collapse in the youth bars before then would mean the platform is losing players, not that the players stopped existing."
              : "Tiers are football's, so this sport is shown by age alone."}
          </p>
        </Card>
      </div>

      {academies.length > 0 ? (
      <Card>
        <SectionTitle
          action={<span className="text-xs text-slate-500">least current first</span>}
        >
          Academies, by data quality
        </SectionTitle>
        <Table>
          <thead>
            <tr>
              <Th>Academy</Th>
              <Th>Governorate</Th>
              <Th>Players</Th>
              <Th>Last submission</Th>
              <Th>Median staleness</Th>
              <Th>Consent complete</Th>
              <Th>Flags</Th>
            </tr>
          </thead>
          <tbody>
            {academies.map((a) => (
              <tr key={a.organization.id} className="hover:bg-slate-900/40">
                <Td className="font-semibold text-slate-100">{a.organization.name}</Td>
                <Td>{regionName[a.organization.region ?? ""] ?? "not set"}</Td>
                <Td className="tabular-nums">{a.playerCount}</Td>
                <Td
                  className={cx(
                    "tabular-nums",
                    (a.lastSubmissionDays ?? 0) >= STALE_DAYS && "font-semibold text-amber-400",
                  )}
                >
                  {a.lastSubmissionDays == null ? "adults only" : `${a.lastSubmissionDays} days`}
                </Td>
                <Td className="tabular-nums">
                  {a.medianStalenessDays == null ? "adults only" : `${a.medianStalenessDays} days`}
                </Td>
                <Td
                  className={cx(
                    "tabular-nums",
                    a.consentCompletePct < 70 && "font-semibold text-amber-400",
                  )}
                >
                  {a.consentCompletePct}%
                </Td>
                <Td className="tabular-nums">{a.openFlags}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <p className="mt-3 text-xs text-slate-500">
          Sorted worst first on purpose. A federation officer opens this to find who needs a phone
          call, and sorting by size would bury the problem under the well run academies. Measuring
          dates count only players under 18, because an adult&apos;s height does not change.
        </p>
      </Card>
      ) : null}
    </div>
  );
}

/** The youngest age with a professional player, read from the data rather than assumed. */
function firstPro(rows: { age: number; pro: number }[]): number | null {
  const row = rows.find((r) => r.pro > 0);
  return row ? row.age : null;
}
