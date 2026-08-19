"use client";

/**
 * Player profile. See docs/wireframes/04-player-profile.html.
 *
 * The screen the whole system exists to produce. Four roles see it and they do not all see the
 * same thing, but which parts are withheld is decided by the API through the `permissions`
 * object on the response. This component renders what it is given. It never infers permission
 * from the role, because anything enforced only in the browser is not enforced.
 *
 * Two rules held throughout: the forecast is drawn as a widening band and never as a bare line,
 * and every flag carries the sentence that explains why it fired.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { GrowthChart, PercentileBar } from "@/components/charts";
import {
  Avatar,
  Banner,
  Button,
  Card,
  Chip,
  Label,
  SectionTitle,
  Skeleton,
  Stub,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { getProfile } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { num, ordinal, shortDate } from "@/lib/format";
import type { PlayerProfile } from "@/lib/types";

export default function PlayerProfilePage({ params }: { params: { id: string } }) {
  const { user } = useAuth();
  const [data, setData] = useState<PlayerProfile | null | "missing">(null);

  useEffect(() => {
    let alive = true;
    getProfile(params.id).then((p) => alive && setData(p ?? "missing"));
    return () => {
      alive = false;
    };
  }, [params.id]);

  if (data === null) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24" />
        <Skeleton className="h-56" />
        <Skeleton className="h-40" />
      </div>
    );
  }

  if (data === "missing") {
    return (
      <Card>
        <p className="text-sm text-slate-400">
          No player with that id. It may have been merged into another record.
        </p>
      </Card>
    );
  }

  const p = data.player;
  const isOwnProfile = user?.linkedPlayerId === p.id;
  // A player looking at their own record does not see the model's flags about them. See the
  // open question on fairness in the wireframe: there is no route for them to dispute one yet.
  const showFlags = data.permissions.canSeeFlags && !isOwnProfile;

  const metricKeys = Array.from(
    new Set(data.performance.flatMap((e) => Object.keys(e.metrics))),
  );

  return (
    <div className="flex flex-col gap-5">
      {/* identity */}
      <div className="flex flex-wrap items-start gap-4">
        <Avatar size={72} />
        <div className="flex min-w-[16rem] flex-1 flex-col gap-2">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h1 className="text-2xl font-bold leading-tight tracking-tight">{p.fullName}</h1>
              <p className="text-sm text-slate-500">
                {data.organizationName}
                {p.position ? ` · ${p.position}` : ""}
                {p.tier ? ` · ${p.tier} tier` : ""}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Link href={`/compare?players=${p.id}`}>
                <Button variant="ghost">Compare</Button>
              </Link>
              {data.permissions.canLog ? <Button>Log measurement</Button> : null}
            </div>
          </div>

          <div className="flex flex-wrap gap-1.5">
            <Chip tone="brand">{data.ageLabel}</Chip>
            {data.latest.heightCm ? <Chip>{data.latest.heightCm} cm</Chip> : null}
            {data.latest.weightKg ? <Chip>{data.latest.weightKg} kg</Chip> : null}
            {p.nationality.map((n) => (
              <Chip key={n}>{n}</Chip>
            ))}
            {p.isEgyptEligible ? <Chip tone="brand">Egypt eligible</Chip> : null}
            {/* Minor status sits here, not in a settings tab. Anyone on this page should know
                within a second that they are looking at a child's record. */}
            {p.isMinor ? <Chip tone="warn">minor</Chip> : null}
          </div>
        </div>
      </div>

      {/* flags */}
      {showFlags && data.flags.length > 0 ? (
        <Banner tone="info" title="What the models are saying">
          <div className="mb-2 flex flex-wrap gap-1.5">
            {data.flags.map((f) => (
              <Chip key={f.type} tone="brand">
                {f.label}
                {f.confidence != null ? (
                  <span className="ml-1 tabular-nums text-slate-400">
                    {f.confidence.toFixed(2)}
                  </span>
                ) : null}
              </Chip>
            ))}
          </div>
          {data.flagReason ? <p className="text-slate-300">{data.flagReason}</p> : null}
          <p className="mt-1 text-xs text-slate-500">
            A flag is a claim, not a verdict. It is generated from the measurements below.
          </p>
        </Banner>
      ) : null}

      {/* growth and maturity */}
      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <Card>
          <SectionTitle action={<span className="text-xs text-slate-500">3 years</span>}>
            Height over time
          </SectionTitle>
          <GrowthChart series={data.growth} />
          <p className="mt-2 text-xs text-slate-500">
            The forecast is drawn as a widening band because that is what the model actually
            knows. A line would imply a confidence it does not have.
          </p>
        </Card>

        <Card>
          <SectionTitle>Maturity</SectionTitle>
          {data.maturity ? (
            <div className="flex flex-col gap-3">
              <div>
                <Label>Offset against peers</Label>
                <p className="text-2xl font-bold tabular-nums">
                  <Stub>
                    {data.maturity.offsetYears > 0 ? "+" : ""}
                    {data.maturity.offsetYears.toFixed(1)} years
                  </Stub>
                </p>
                <p className="text-xs text-slate-500">
                  {data.maturity.offsetYears < -0.5
                    ? "Behind his age group, which is the late bloomer signal. Short for his age is not the same as short."
                    : "In line with his age group."}
                </p>
              </div>
              <div>
                <Label>Predicted adult height</Label>
                <p className="text-xl font-bold tabular-nums">
                  <Stub>
                    {data.maturity.predictedAdultHeightCm} &plusmn; {data.maturity.errorCm} cm
                  </Stub>
                </p>
              </div>
              <p className="rounded-md border border-slate-800 bg-slate-900/60 px-3 py-2 text-xs text-slate-500">
                Method: {data.maturity.method}. The ML track has not settled this, so treat the
                number as a placeholder for a real estimate.
              </p>
            </div>
          ) : (
            <p className="text-sm text-slate-500">No maturity estimate for this player.</p>
          )}
        </Card>
      </div>

      {/* percentiles */}
      <Card>
        <SectionTitle>Against his age group</SectionTitle>
        <div className="grid gap-4 sm:grid-cols-2">
          {data.percentiles.map((pc) => (
            <div key={pc.metric} className="flex flex-col gap-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm">{pc.label}</span>
                <span className="tabular-nums text-sm text-slate-400">
                  {num(pc.value, pc.unit === "s" ? 2 : pc.value < 10 ? 2 : 0)} {pc.unit}
                  <span className="ml-2 font-semibold text-slate-200">
                    {ordinal(pc.percentile)}
                  </span>
                </span>
              </div>
              <PercentileBar percentile={pc.percentile} higherIsBetter={pc.higherIsBetter} />
              <span className="text-[0.7rem] text-slate-600">vs {pc.population}</span>
            </div>
          ))}
        </div>
      </Card>

      {/* performance, driven by the sport module */}
      <Card>
        <SectionTitle
          action={
            <Chip tone="brand">
              {data.performance[0]?.schemaRef ?? p.primarySport}
            </Chip>
          }
        >
          Performance
        </SectionTitle>
        {data.performance.length === 0 ? (
          <p className="text-sm text-slate-500">No performance entries recorded.</p>
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Period</Th>
                  {metricKeys.map((k) => (
                    <Th key={k}>{k.replace(/_/g, " ")}</Th>
                  ))}
                  <Th>Source</Th>
                </tr>
              </thead>
              <tbody>
                {data.performance.map((e) => (
                  <tr key={e.id}>
                    <Td className="whitespace-nowrap">
                      {shortDate(e.periodStart)}
                      {e.periodEnd ? ` to ${shortDate(e.periodEnd)}` : ""}
                    </Td>
                    {metricKeys.map((k) => (
                      <Td key={k} className="tabular-nums">
                        {e.metrics[k] ?? "-"}
                      </Td>
                    ))}
                    <Td className="whitespace-nowrap text-slate-500">
                      {e.source.replace(/_/g, " ")}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <p className="mt-2 text-xs text-slate-500">
              These columns are read from the entry&apos;s metrics rather than hard coded. Load a
              table tennis player and the same component renders matches, sets, and rally length
              from the same JSON field. If this section needed a rewrite to add a sport, the
              architecture would have failed.
            </p>
          </>
        )}
      </Card>

      {/* assistant summary */}
      {data.summary ? (
        <Card className="bg-slate-900/70">
          <SectionTitle>Summary</SectionTitle>
          <p className="text-sm leading-relaxed text-slate-300">{data.summary}</p>
          <p className="mt-2 text-xs text-slate-500">
            Generated from this player&apos;s record. It rephrases numbers already on this page
            and introduces none of its own. Not a scouting opinion.
          </p>
        </Card>
      ) : null}

      {/* provenance */}
      <Card className="bg-slate-900/40">
        <SectionTitle>Where this data came from</SectionTitle>
        <div className="flex flex-wrap gap-1.5">
          <Chip>{data.provenance.measurementCount} measurements</Chip>
          <Chip>{data.provenance.performanceCount} performance entries</Chip>
          {data.provenance.consents.map((c) => (
            <Chip key={c.purpose} tone={c.granted ? "good" : "warn"}>
              {c.purpose.replace(/_/g, " ")}: {c.granted ? "granted" : "not granted"}
            </Chip>
          ))}
        </div>
        <p className="mt-2 text-xs text-slate-500">
          How much data there is, and what consent exists, decide how much anyone should trust
          the rest of this screen. That is why it is on the page rather than in an admin view.
        </p>
      </Card>
    </div>
  );
}
