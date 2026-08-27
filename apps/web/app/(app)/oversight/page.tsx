"use client";

/**
 * Federation oversight. See docs/wireframes/07-federation-oversight.html.
 *
 * The national view, and not a scouting tool. It answers whether the country's talent data is
 * any good: who is covered, who is missing, and which academies are actually keeping records.
 *
 * Two deliberate choices. Staleness is the headline rather than player count, because a
 * federation can grow the count by onboarding one large academy and learn nothing. And coverage
 * is shown per million people rather than as a raw total, because Cairo will always have the
 * most tracked players and the interesting fact is the governorate with five million people and
 * eleven of them.
 */

import { useEffect, useState } from "react";
import { RatioBars, StackedAges } from "@/components/charts";
import {
  Banner,
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
import { getOversight } from "@/lib/api";
import { STALE_DAYS, cx } from "@/lib/format";
import type { OversightSummary } from "@/lib/types";

export default function OversightPage() {
  const [data, setData] = useState<OversightSummary | null>(null);

  useEffect(() => {
    let alive = true;
    getOversight().then((d) => alive && setData(d));
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
    (a, b) => b.medianStalenessDays - a.medianStalenessDays,
  );

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">National coverage</h1>
          <p className="text-sm text-slate-500">Football, all tiers, season 2025 to 2026</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Chip tone="brand" active>
            football
          </Chip>
          <Chip title="Table tennis oversight uses the same screen with different metrics.">
            table tennis
          </Chip>
          <Button
            variant="ghost"
            title="A national export of minors' data is the highest risk action in the product. Not built."
            disabled
          >
            Export
          </Button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Players tracked" value={data.playersTracked.toLocaleString("en-GB")} />
        <Stat label="Academies reporting" value={data.academiesReporting} />
        <Stat
          label={`Stale over ${STALE_DAYS} days`}
          value={`${data.stalePct}%`}
          tone={data.stalePct > 15 ? "warn" : "good"}
          hint="the number that says whether any of this is trustworthy"
        />
        <Stat label="Open flags" value={data.openFlags} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionTitle>Coverage by governorate</SectionTitle>
          <RatioBars
            rows={data.byRegion.map((r) => ({
              label: r.region,
              value: r.players,
              per: r.populationM,
            }))}
          />
          <p className="mt-3 text-xs text-slate-500">
            Players tracked per million people. Amber marks the governorates where the platform
            has barely reached. Where the gaps are matters more than where the totals are.
          </p>
          <Banner tone="info">
            This panel needs a region field on Organization, which the schema does not have. It is
            drawn from synthetic values. Raised in docs/wireframes/README.md.
          </Banner>
        </Card>

        <Card>
          <SectionTitle>Players by age and tier</SectionTitle>
          <StackedAges rows={data.byAgeTier} />
          <p className="mt-3 text-xs text-slate-500">
            The professional tier only begins to appear at 16, which is expected. A collapse in
            the youth bars before then would mean the platform is losing players, not that the
            players stopped existing.
          </p>
        </Card>
      </div>

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
                <Td>{a.organization.region ?? "unknown"}</Td>
                <Td className="tabular-nums">{a.playerCount}</Td>
                <Td
                  className={cx(
                    "tabular-nums",
                    a.lastSubmissionDays >= STALE_DAYS && "font-semibold text-amber-400",
                  )}
                >
                  {a.lastSubmissionDays} days
                </Td>
                <Td className="tabular-nums">{a.medianStalenessDays} days</Td>
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
          call, and sorting by size would bury the problem under the well run academies.
        </p>
      </Card>

      <Card className="bg-slate-900/40">
        <SectionTitle>Diaspora watchlist</SectionTitle>
        <div className="flex flex-wrap gap-1.5">
          <Chip tone="brand">{data.diaspora.total} Egypt eligible players abroad</Chip>
          <Chip>{data.diaspora.uncappedUnder21} uncapped and under 21</Chip>
          <Chip tone="good">{data.diaspora.newThisMonth} new this month</Chip>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          The only place in the product where this is a list somebody is responsible for rather
          than a set of search results. Tracking Egypt eligible players abroad is a stated reason
          the project exists, and nobody currently does it.
        </p>
      </Card>
    </div>
  );
}
