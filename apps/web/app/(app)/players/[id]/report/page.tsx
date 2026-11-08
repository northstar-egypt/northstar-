"use client";

/**
 * A pro player's scouting report (apps/api/app/services/scouting_report.py, running
 * ml/pro/report.py): the verdict first, then the evidence behind it.
 *
 * Every grade and sentence is a rule over the numbers shown, and the rules are stated at the foot
 * of the page. What the data cannot say is said too, rather than left out. The API decides who
 * gets a report; when there is none, the page shows the API's reason.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { PercentileBar } from "@/components/charts";
import { Pitch } from "@/components/pitch";
import { Avatar, Banner, Card, Chip, SectionTitle, Skeleton } from "@/components/ui";
import { getProfile, getScoutingReport } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cx, ordinal } from "@/lib/format";
import { ROLE_IDENTITY } from "@/lib/roles";
import type { PlayerProfile, ReportEvidence, ScoutingReport } from "@/lib/types";

const GRADE_COLOUR: Record<string, string> = {
  A: "text-emerald-300",
  B: "text-emerald-400",
  C: "text-slate-200",
  D: "text-amber-400",
};

function amount(e: ReportEvidence, value: number): string {
  return e.unit === "%" ? `${value}%` : `${value} per 90`;
}

function EvidenceLine({ e }: { e: ReportEvidence }) {
  return (
    <li className="text-sm text-slate-300">
      <span className="font-semibold text-slate-100">{e.label}</span>
      {e.lowReliability ? " *" : ""}: {amount(e, e.value)},{" "}
      <span className="tabular-nums">{ordinal(e.percentile)}</span> percentile{" "}
      <span className="text-slate-500">(median {amount(e, e.median)})</span>
    </li>
  );
}

export default function ScoutingReportPage() {
  const playerId = String(useParams().id ?? "");
  const { user } = useAuth();
  const [profile, setProfile] = useState<PlayerProfile | null>(null);
  const [report, setReport] = useState<ScoutingReport | null | "loading">("loading");
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getProfile(playerId).then((p) => {
      if (alive && p && !("mergedInto" in p)) setProfile(p);
    });
    getScoutingReport(playerId)
      .then((r) => {
        if (!alive) return;
        setReport(r?.report ?? null);
        setNote(r?.note ?? (r ? null : "No player with that id."));
      })
      .catch((e) => {
        if (!alive) return;
        setReport(null);
        setNote(e.message);
      });
    return () => {
      alive = false;
    };
  }, [playerId]);

  const accent = ROLE_IDENTITY[user?.role ?? "scout"];
  const back = (
    <Link href={`/players/${playerId}`} className="text-sm text-sky-300 hover:underline">
      Back to the profile
    </Link>
  );

  if (report === "loading") return <Skeleton className="h-96" />;
  if (report === null) {
    return (
      <div className="flex flex-col gap-3">
        {back}
        <Banner tone="info" title="No scouting report">
          {note}
        </Banner>
      </div>
    );
  }

  const graded = report.areas.filter((a) => a.graded);
  const others = report.areas.filter((a) => !a.graded);
  const finishing = report.finishing;
  const anyStarred = report.areas.some((a) => a.evidence.some((e) => e.lowReliability));

  return (
    <div className="flex flex-col gap-5">
      {back}

      <div className="flex flex-wrap items-start gap-4">
        <Avatar size={64} name={profile?.player.fullName} />
        <div className="min-w-[14rem] flex-1">
          <p className={cx("text-xs font-medium uppercase tracking-widest", accent.text)}>Scouting report</p>
          <h1 className="text-2xl font-bold leading-tight tracking-tight"><bdi>{profile?.player.fullName}</bdi></h1>
          <p className="text-sm text-slate-500">
            {[report.club, report.groupLabel, profile ? `age ${profile.ageLabel}` : null].filter(Boolean).join(" · ")}
          </p>
          <p className="text-sm text-slate-500">
            {report.competition} {report.season}, compared with {report.population} {report.groupLabel.toLowerCase()},{" "}
            {report.minutes.toLocaleString()} minutes
          </p>
        </div>
      </div>

      {/* The verdict comes first: a scout should have it in ten seconds. */}
      <Card className={cx("border-l-4", accent.border)}>
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">Current level</p>
            <p className={cx("text-5xl font-bold leading-none", GRADE_COLOUR[report.levelGrade ?? ""] ?? "text-slate-200")}>
              {report.levelGrade ?? "n/a"}
            </p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">Recommendation</p>
            <p className="text-2xl font-bold">{report.recommendation ?? "None"}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">Confidence</p>
            <p className="text-lg font-semibold capitalize">{report.confidence}</p>
            <p className="text-xs text-slate-500">from {report.minutes.toLocaleString()} minutes</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {graded.map((a) => (
              <div key={a.key} className="rounded-md border border-slate-800 px-3 py-1.5 text-center">
                <p className={cx("text-xl font-bold leading-none", GRADE_COLOUR[a.grade ?? ""] ?? "text-slate-400")}>
                  {a.grade ?? "n/a"}
                </p>
                <p className="mt-1 text-[0.7rem] text-slate-400">{a.label}</p>
              </div>
            ))}
          </div>
        </div>
        <p className="mt-4 text-slate-200">{report.summary}</p>
        {report.young && report.recommendation !== "Shortlist" ? (
          <p className="mt-1 text-sm text-slate-400">Aged under 23: development years ahead, so the level can still rise.</p>
        ) : null}
        <p className="mt-2 text-xs text-slate-500">A claim to check, not a decision: the data sees only part of a player.</p>
        </div>
        <Pitch group={report.group} groupLabel={report.groupLabel} className={accent.text} />
        </div>
      </Card>

      <div className="grid gap-5 md:grid-cols-2">
        <Card>
          <SectionTitle>Strengths</SectionTitle>
          {report.strengths.length === 0 ? (
            <p className="text-sm text-slate-400">Nothing at the 70th percentile or above.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {report.strengths.map((e) => (
                <EvidenceLine key={e.key} e={e} />
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <SectionTitle>Weaknesses</SectionTitle>
          {report.weaknesses.length === 0 ? (
            <p className="text-sm text-slate-400">Nothing at the 30th percentile or below.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {report.weaknesses.map((e) => (
                <EvidenceLine key={e.key} e={e} />
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card>
        <SectionTitle>The numbers, against the position</SectionTitle>
        <p className="mb-4 text-xs text-slate-500">
          Each bar is where the player ranks among {report.population} {report.groupLabel.toLowerCase()} in{" "}
          {report.competition} {report.season}. The current level is graded on the areas this role needs; the others
          are shown for information.
        </p>
        <div className="grid gap-x-8 gap-y-6 md:grid-cols-2">
          {[...graded, ...others].map((area) => (
            <div key={area.key}>
              <div className="mb-2 flex items-baseline justify-between gap-2">
                <h3 className="font-semibold">
                  {area.label}
                  {area.graded ? <span className={cx("ml-2 text-xs font-normal", accent.text)}>graded for this role</span> : null}
                </h3>
                <span className="text-sm tabular-nums text-slate-400">
                  {area.grade ?? "n/a"}
                  {area.score != null ? `, average ${ordinal(Math.round(area.score))}` : ""}
                </span>
              </div>
              <div className="flex flex-col gap-2.5">
                {area.evidence.map((e) => (
                  <div key={e.key}>
                    <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
                      <span className="text-slate-300">
                        {e.label}
                        {e.lowReliability ? " *" : ""}
                      </span>
                      <span className="tabular-nums text-slate-400">
                        {amount(e, e.value)}
                        <span className="ml-2 font-semibold text-slate-200">{ordinal(e.percentile)}</span>
                      </span>
                    </div>
                    <PercentileBar percentile={e.percentile} higherIsBetter />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        {anyStarred ? (
          <p className="mt-4 text-xs text-slate-500">
            * Repeats poorly from one half of a season to the other, so weigh it less.
          </p>
        ) : null}
      </Card>

      <div className="grid gap-5 md:grid-cols-2">
        <Card>
          <SectionTitle>Finishing and form</SectionTitle>
          <p className="text-sm text-slate-300">
            {finishing.seasons > 1 ? `Over ${finishing.seasons} seasons` : "This season"}: {finishing.npGoals} non-penalty goals
            from chances worth {finishing.npxg.toFixed(1)}.{" "}
            {finishing.low != null && finishing.high != null
              ? `An ordinary finisher scores ${finishing.low} to ${finishing.high} from those, so this is ${
                  finishing.verdict === "in line" ? "within what chance makes" : `${finishing.verdict} expected`
                }.`
              : "Too few chances to judge the finishing."}
          </p>
          {report.breakout ? (
            <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-slate-300">
              {report.breakout.flagged ? <Chip tone="brand">Breakout</Chip> : null}
              <span>{report.breakout.flagged ? `${report.breakout.reason}.` : `No breakout flagged: ${report.breakout.reason}.`}</span>
            </div>
          ) : null}
        </Card>
        <Card>
          <SectionTitle>What would change this verdict</SectionTitle>
          <ul className="flex list-disc flex-col gap-1.5 pl-4 text-sm text-slate-300">
            {report.wouldChange.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Card>
      </div>

      <Card>
        <SectionTitle>Not in our data</SectionTitle>
        <ul className="flex list-disc flex-col gap-1 pl-4 text-sm text-slate-400">
          {report.notInData.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </Card>

      <p className="text-xs text-slate-500">
        How this was built: per-90 rates and shares from the league season, as percentiles among players of the same
        position group, league and season with 450 minutes or more. Grades: A at an average of 85 or more, B at 70, C at
        50, D below. The current level averages the areas the role needs. Shortlist at a level of 70 or more, Monitor at
        50, Not now below. Confidence: high at 2,000 minutes, medium at 1,000, low below. Every sentence is a rule over
        these numbers.
      </p>
    </div>
  );
}
