"use client";

/**
 * A pro player's scouting report (apps/api/app/services/scouting_report.py, running
 * ml/pro/report.py), laid out as a report: the verdict and three lines read from the numbers,
 * then the evidence (every statistic as a percentile, then the pitch), then who plays alike,
 * finishing, the seasons on record and what the data cannot see.
 *
 * Every grade and sentence is a rule over the numbers shown, and the rules are stated at the foot
 * of the page. Where the season has no event locations (the synthetic league), the pitch section
 * says so instead of drawing empty maps. The API decides who gets a report; when there is none,
 * the page shows the API's reason.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  AREA_COLOURS,
  CHANCE,
  FinishingLine,
  GOAL,
  KeyPassMap,
  PercentilePizza,
  ShotMap,
  TouchHeatMap,
} from "@/components/pro-charts";
import { Avatar, Banner, Skeleton } from "@/components/ui";
import { getProfile, getScoutingReport } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cx } from "@/lib/format";
import { ROLE_IDENTITY } from "@/lib/roles";
import type { PlayerProfile, ReportEvidence, ScoutingReport } from "@/lib/types";

const GRADE_COLOUR: Record<string, string> = {
  A: "text-emerald-300",
  B: "text-emerald-400",
  C: "text-slate-100",
  D: "text-amber-400",
};

const CASE_STYLE = {
  strength: { mark: "+", box: "bg-emerald-950 text-emerald-400" },
  weakness: { mark: "−", box: "bg-amber-950 text-amber-400" },
  caution: { mark: "!", box: "bg-sky-950 text-sky-300" },
} as const;

// min-w-0: a card in a grid must not grow to its widest child (the seasons table scrolls instead).
const panel = "min-w-0 rounded-2xl border border-slate-800 bg-slate-900/70";

function amount(e: ReportEvidence): string {
  return e.unit === "%" ? `${e.value}%` : e.value.toFixed(2);
}

function barColour(p: number): string {
  if (p >= 70) return "bg-emerald-400";
  if (p <= 30) return "bg-amber-500";
  return "bg-sky-400";
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-lg bg-slate-950/70 px-3 py-2.5">
      <div className="text-[11px] text-slate-400">{label}</div>
      <div className={cx("font-mono text-xl font-bold tabular-nums", accent)}>{value}</div>
    </div>
  );
}

export default function ScoutingReportPage() {
  const playerId = String(useParams().id ?? "");
  const { user } = useAuth();
  const [profile, setProfile] = useState<PlayerProfile | null>(null);
  const [report, setReport] = useState<ScoutingReport | null | "loading">("loading");
  const [note, setNote] = useState<string | null>(null);
  const [choice, setChoice] = useState<{ competition: string; season: string } | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    getProfile(playerId).then((p) => {
      if (alive && p && !("mergedInto" in p)) setProfile(p);
    });
    return () => {
      alive = false;
    };
  }, [playerId]);

  useEffect(() => {
    let alive = true;
    getScoutingReport(playerId, choice)
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
  }, [playerId, choice]);

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

  const name = profile?.player.fullName ?? "";
  const pitch = report.pitch;
  const hasPitch = !!pitch && (pitch.shots.length > 0 || pitch.keyPasses.length > 0 || pitch.touchMap !== null);
  const goals = pitch?.shots.filter((s) => s.outcome === "goal").length ?? 0;
  const xg = pitch?.shots.reduce((t, s) => t + (s.xg ?? 0), 0) ?? 0;
  const assists = pitch?.keyPasses.filter((k) => k.outcome === "assist").length ?? 0;
  const xa = pitch?.keyPasses.reduce((t, k) => t + (k.xa ?? 0), 0) ?? 0;
  const actions = pitch?.touchMap?.reduce((a, b) => a + b, 0) ?? 0;
  const ordered = [...report.areas.filter((a) => a.graded), ...report.areas.filter((a) => !a.graded)];
  const anyStarred = report.areas.some((a) => a.evidence.some((e) => e.lowReliability));
  const finishing = report.finishing;
  const fromStatsBomb = pitch?.eventSource === "statsbomb";

  return (
    <div className="flex flex-col gap-7">
      {back}

      {/* The verdict: who, how good, and the three lines a scout reads first. */}
      <section aria-label="Verdict" className={cx(panel, "overflow-hidden")}>
        <div className="grid lg:grid-cols-2">
          <div className="flex flex-col gap-5 p-6 sm:p-8">
            <div className="flex items-center gap-5">
              <Avatar size={80} name={name} />
              <div className="min-w-0">
                <p className={cx("text-xs font-semibold uppercase tracking-[0.14em]", accent.text)}>Scouting report</p>
                <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl"><bdi>{name}</bdi></h1>
                <p className="text-sm text-slate-400">
                  {[profile?.player.position, report.club, profile?.ageLabel ? (/^\d/.test(profile.ageLabel) ? `age ${profile.ageLabel}` : profile.ageLabel) : null]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
            </div>
            {report.seasons.length > 1 ? (
              <div role="tablist" aria-label="Season" className="flex flex-wrap gap-2">
                {report.seasons.map((s) => (
                  <button
                    key={`${s.competition}-${s.season}`}
                    type="button"
                    role="tab"
                    aria-selected={s.selected}
                    disabled={!s.gradable || s.selected}
                    title={s.gradable ? undefined : "Too few minutes to grade"}
                    onClick={() => setChoice({ competition: s.competition, season: s.season })}
                    className={cx(
                      "min-h-[44px] rounded-lg border px-3.5 py-2 text-left",
                      s.selected
                        ? "border-amber-500 bg-amber-950/60 text-amber-100"
                        : s.gradable
                          ? "border-slate-700 text-slate-200 hover:border-slate-500"
                          : "cursor-not-allowed border-slate-800 text-slate-500",
                    )}
                  >
                    <span className="block text-sm font-semibold">
                      {s.competition} {s.season}
                    </span>
                    <span className="block text-xs opacity-80">
                      {[s.club, `${s.minutes.toLocaleString()} min`].filter(Boolean).join(" · ")}
                    </span>
                  </button>
                ))}
              </div>
            ) : null}
            <p className="text-sm text-slate-400">
              {report.competition} {report.season}: graded against {report.population}{" "}
              {report.groupLabel.toLowerCase()} with 450+ minutes, from {report.minutes.toLocaleString()} minutes.
            </p>
          </div>

          <div className="flex flex-col gap-5 border-t border-slate-800 bg-slate-950/40 p-6 sm:p-8 lg:border-l lg:border-t-0">
            <div className="flex flex-wrap items-center gap-6">
              <div className="flex h-28 w-28 flex-col items-center justify-center rounded-2xl border border-slate-700 bg-slate-950">
                <span className={cx("text-6xl font-bold leading-none", GRADE_COLOUR[report.levelGrade ?? ""] ?? "text-slate-300")}>
                  {report.levelGrade ?? "n/a"}
                </span>
                {report.level != null ? (
                  <span className="mt-1.5 text-[11px] tracking-wider text-slate-400">LEVEL {Math.round(report.level)}/100</span>
                ) : null}
              </div>
              <div>
                <p className="text-xs uppercase tracking-wider text-slate-400">Recommendation</p>
                <p className="text-3xl font-bold text-amber-200">{report.recommendation ?? "None"}</p>
                <p className="text-sm capitalize text-slate-300">{report.confidence} confidence</p>
              </div>
            </div>
            {report.case.length > 0 ? (
              <ul className="flex flex-col gap-3.5">
                {report.case.map((line) => (
                  <li key={line.headline} className="flex items-start gap-3.5">
                    <span
                      aria-hidden
                      className={cx("flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-sm font-bold", CASE_STYLE[line.kind].box)}
                    >
                      {CASE_STYLE[line.kind].mark}
                    </span>
                    <p className="text-[15px] leading-relaxed">
                      <span className="font-semibold">{line.headline}</span>{" "}
                      <span className="text-slate-400">{line.detail}</span>
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-slate-300">{report.summary}</p>
            )}
            <p className="text-xs text-slate-500">Each line is read from the numbers below. A claim to check, not a decision.</p>
          </div>
        </div>
      </section>

      {/* Every statistic against the position. */}
      <section aria-label="Against the position" className="flex flex-col gap-4">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-xl font-bold tracking-tight">
            Against {report.population} {report.competition} {report.groupLabel.toLowerCase()}
          </h2>
          <span className="text-sm text-slate-400">Percentile: higher is better on every statistic.</span>
        </div>
        <div className="grid gap-5 xl:grid-cols-2">
          <div className={cx(panel, "flex flex-col gap-3 p-5")}>
            <PercentilePizza areas={report.areas} />
            <div className="flex flex-wrap justify-center gap-x-4 gap-y-1.5 text-xs text-slate-300">
              {report.areas.map((a, i) => (
                <span key={a.key} className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-sm" style={{ background: AREA_COLOURS[i % AREA_COLOURS.length] }} />
                  {a.label}
                </span>
              ))}
              <span className="text-slate-500">dashed ring = middle of the group</span>
            </div>
          </div>
          <div className={cx(panel, "flex flex-col gap-5 p-5")}>
            {ordered.map((area, i) => (
              <div key={area.key} className={cx("flex flex-col gap-2", i === report.areas.filter((a) => a.graded).length && "border-t border-slate-800 pt-4")}>
                <div className="flex items-baseline justify-between">
                  <span className={cx("text-sm font-semibold", !area.graded && "text-slate-300")}>
                    {area.label}
                    {area.graded ? <span className={cx("ml-2 text-[11px] font-medium tracking-wider", accent.text)}>GRADED</span> : null}
                  </span>
                  <span className={cx("text-sm font-bold tabular-nums", GRADE_COLOUR[area.grade ?? ""] ?? "text-slate-400")}>
                    {area.grade ?? "n/a"}
                    {area.score != null ? ` · ${Math.round(area.score)}` : ""}
                  </span>
                </div>
                {area.evidence.map((e) => (
                  <div key={e.key} className="grid grid-cols-[minmax(0,9.5rem)_4rem_minmax(0,1fr)_2.25rem] items-center gap-2.5 text-[13px]">
                    <span className="truncate text-slate-300">
                      {e.label}
                      {e.lowReliability ? "*" : ""}
                    </span>
                    <span className="font-mono tabular-nums text-slate-100">{amount(e)}</span>
                    <span className="relative block h-2 rounded bg-slate-800" title={`median ${e.unit === "%" ? `${e.median}%` : e.median}`}>
                      <span className={cx("absolute inset-y-0 left-0 rounded", barColour(e.percentile))} style={{ width: `${e.percentile}%` }} />
                      <span className="absolute -inset-y-1 left-1/2 w-px bg-slate-500" aria-hidden />
                    </span>
                    <span className="text-right font-mono font-semibold tabular-nums">{e.percentile}</span>
                  </div>
                ))}
              </div>
            ))}
            <p className="text-xs text-slate-500">
              The line on each bar is the group&apos;s middle.
              {anyStarred ? " * Repeats poorly from one half season to the next: weigh it less." : ""} Graded areas are the
              ones this position is judged on.
            </p>
          </div>
        </div>
      </section>

      {/* The pitch: where the season happened, when the data has locations. */}
      <section aria-label="On the pitch" className="flex flex-col gap-4">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-xl font-bold tracking-tight">On the pitch</h2>
          {hasPitch ? (
            <span className="text-sm text-slate-400">
              {pitch!.matches} {report.competition} matches · every event placed{fromStatsBomb ? " by StatsBomb" : ""}
            </span>
          ) : null}
        </div>
        {!hasPitch ? (
          <div className={cx(panel, "p-5 text-sm text-slate-400")}>
            No event locations for {report.competition} {report.season}: this league&apos;s figures are season totals, so
            there is no shot map or heat map to draw. Leagues with event data (StatsBomb) have them.
          </div>
        ) : (
          <div className="grid gap-5 lg:grid-cols-3">
            <div className={cx(panel, "flex flex-col gap-3 p-5")}>
              <div className="flex items-baseline justify-between">
                <h3 className="font-semibold">Shots</h3>
                <span className="text-xs text-slate-400">
                  size = chance quality{pitch!.xgModel === "northstar" ? ", NorthStar xG" : ""}
                </span>
              </div>
              <ShotMap shots={pitch!.shots} />
              <div className="grid grid-cols-4 gap-2">
                <Stat label="Shots" value={String(pitch!.shots.length)} />
                <Stat label="Goals" value={String(goals)} accent="text-amber-300" />
                <Stat label="xG per shot" value={pitch!.shots.length ? (xg / pitch!.shots.length).toFixed(2) : "n/a"} />
                <Stat label="Conversion" value={pitch!.shots.length ? `${Math.round((goals / pitch!.shots.length) * 100)}%` : "n/a"} />
              </div>
              <Legend items={[{ colour: GOAL, label: "Goal", filled: true }, { colour: CHANCE, label: "No goal" }]} />
            </div>
            <div className={cx(panel, "flex flex-col gap-3 p-5")}>
              <div className="flex items-baseline justify-between">
                <h3 className="font-semibold">Chances created</h3>
                <span className="text-xs text-slate-400">attacking to the right</span>
              </div>
              <KeyPassMap passes={pitch!.keyPasses} />
              <div className="grid grid-cols-3 gap-2">
                <Stat label="Key passes" value={String(pitch!.keyPasses.length)} />
                <Stat label="Assists" value={String(assists)} accent="text-amber-300" />
                <Stat label="xA" value={xa.toFixed(2)} />
              </div>
              <Legend items={[{ colour: GOAL, label: "Assist", filled: true }, { colour: CHANCE, label: "Pass that led to a shot" }]} />
            </div>
            <div className={cx(panel, "flex flex-col gap-3 p-5")}>
              <div className="flex items-baseline justify-between">
                <h3 className="font-semibold">Where they play</h3>
                <span className="text-xs text-slate-400">attacking to the right</span>
              </div>
              {pitch!.touchMap ? <TouchHeatMap grid={pitch!.touchMap} /> : <p className="text-sm text-slate-400">No touch map.</p>}
              <div className="grid grid-cols-3 gap-2">
                <Stat label="Actions" value={actions.toLocaleString()} />
                <Stat label="Matches" value={String(pitch!.matches)} />
                <Stat label="Minutes" value={report.minutes.toLocaleString()} />
              </div>
              <p className="text-xs text-slate-500">Every event with a location: passes, carries, shots, duels. Brighter = more.</p>
            </div>
          </div>
        )}
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <section aria-label="Plays most like" className={cx(panel, "flex flex-col gap-3 p-6")}>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-lg font-semibold">Plays most like</h2>
            <span className="text-xs text-slate-400">{report.groupLabel.toLowerCase()} with 900+ minutes</span>
          </div>
          {report.similar.length === 0 ? (
            <p className="text-sm text-slate-400">Not enough comparable seasons to say.</p>
          ) : (
            <ul className="flex flex-col">
              {report.similar.map((s) => (
                <li key={`${s.playerId}-${s.season}`} className="grid grid-cols-[2.5rem_minmax(0,1fr)_minmax(4rem,7rem)_3rem] items-center gap-3 border-b border-slate-800 py-2.5 last:border-0">
                  <Avatar size={36} name={s.fullName} />
                  <div className="min-w-0">
                    <Link href={`/players/${s.playerId}/report`} className="block truncate font-semibold hover:underline">
                      <bdi>{s.fullName}</bdi>
                    </Link>
                    <p className="truncate text-xs text-slate-400">
                      {[s.club, `${s.competition} ${s.season}`, `${s.minutes.toLocaleString()} min`].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                  <span className="relative block h-2 rounded bg-slate-800">
                    <span className="absolute inset-y-0 left-0 rounded bg-amber-500" style={{ width: `${Math.max(0, s.similarity)}%` }} />
                  </span>
                  <span className="text-right font-mono font-semibold tabular-nums">{s.similarity}%</span>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-slate-500">
            Alike in style, not level: the same statistics per 90, compared after scaling each across the group. Real
            players are compared only with real players. Tested on half seasons: a player&apos;s own other half is
            among the five closest 43% of the time, against 3% by chance.
            {report.group === "centre_backs"
              ? " Centre backs are the weakest group (21%): their defensive statistics vary a lot from match to match, so weigh this list least."
              : ""}
          </p>
        </section>

        <section aria-label="Finishing" className={cx(panel, "flex flex-col gap-4 p-6")}>
          <h2 className="text-lg font-semibold">Finishing against expected</h2>
          <div className="flex flex-wrap gap-8">
            <div>
              <div className="text-xs text-slate-400">Non-penalty goals</div>
              <div className="font-mono text-4xl font-bold text-amber-300">{finishing.npGoals}</div>
            </div>
            <div>
              <div className="text-xs text-slate-400">Expected (npxG)</div>
              <div className="font-mono text-4xl font-bold text-sky-300">{finishing.npxg.toFixed(2)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-400">Difference</div>
              <div className="font-mono text-4xl font-bold">
                {finishing.npGoals - finishing.npxg >= 0 ? "+" : ""}
                {(finishing.npGoals - finishing.npxg).toFixed(1)}
              </div>
            </div>
          </div>
          {finishing.low != null && finishing.high != null ? (
            <FinishingLine goals={finishing.npGoals} expected={finishing.npxg} low={finishing.low} high={finishing.high} />
          ) : null}
          <p className="text-sm leading-relaxed text-slate-300">
            {finishing.seasons > 1 ? `Across ${finishing.seasons} seasons on record. ` : ""}
            {finishing.low != null && finishing.high != null
              ? finishing.verdict === "in line"
                ? `Within the range ordinary finishing gives (${finishing.low} to ${finishing.high}).`
                : `${finishing.verdict === "above" ? "Above" : "Below"} the range ordinary finishing gives (${finishing.low} to ${finishing.high}, 10th to 90th percentile), which mostly does not last.`
              : "Too few chances to judge the finishing."}
          </p>
        </section>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <section aria-label="Seasons on record" className={cx(panel, "flex flex-col gap-3 p-6")}>
          <h2 className="text-lg font-semibold">Seasons on record</h2>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[30rem] border-collapse text-[13px]">
              <thead>
                <tr className="text-left text-slate-400">
                  <th className="border-b border-slate-700 px-2.5 py-2 font-medium">Competition</th>
                  <th className="border-b border-slate-700 px-2.5 py-2 text-right font-medium">Min</th>
                  <th className="border-b border-slate-700 px-2.5 py-2 text-right font-medium">G</th>
                  <th className="border-b border-slate-700 px-2.5 py-2 text-right font-medium">A</th>
                  <th className="border-b border-slate-700 px-2.5 py-2 text-right font-medium">npxG</th>
                  <th className="border-b border-slate-700 px-2.5 py-2 text-right font-medium">xA</th>
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                {report.seasons.map((s) => (
                  <tr key={`${s.competition}-${s.season}`} className={s.selected ? "bg-amber-950/30" : undefined}>
                    <td className="border-b border-slate-800 px-2.5 py-2.5 font-sans">
                      <span className="font-semibold">
                        {s.competition} {s.season}
                      </span>
                      {s.club ? <span className="text-slate-400"> · {s.club}</span> : null}
                    </td>
                    <td className="border-b border-slate-800 px-2.5 py-2.5 text-right">{s.minutes.toLocaleString()}</td>
                    <td className="border-b border-slate-800 px-2.5 py-2.5 text-right">{s.goals}</td>
                    <td className="border-b border-slate-800 px-2.5 py-2.5 text-right">{s.assists}</td>
                    <td className="border-b border-slate-800 px-2.5 py-2.5 text-right">{s.npxg.toFixed(2)}</td>
                    <td className="border-b border-slate-800 px-2.5 py-2.5 text-right">{s.xa.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {report.seasons.some((s) => !s.gradable) ? (
            <p className="text-xs text-slate-500">Seasons under 450 minutes are listed but too short to grade.</p>
          ) : null}
        </section>

        <section aria-label="What this data cannot see" className={cx(panel, "flex flex-col gap-3 p-6")}>
          <h2 className="text-lg font-semibold">What this data cannot see</h2>
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-slate-300">
            {report.notInData.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
          {report.wouldChange.length > 0 ? (
            <>
              <h3 className="mt-2 text-sm font-semibold">What would change this verdict</h3>
              <ul className="list-disc space-y-1.5 pl-5 text-sm text-slate-300">
                {report.wouldChange.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </>
          ) : null}
        </section>
      </div>

      <p className="text-xs leading-relaxed text-slate-500">
        How this was built: per-90 rates and shares from the season, as percentiles among players of the same position
        group, competition and season with 450 minutes or more. Grades: A at an average of 85 or more, B at 70, C at 50, D
        below. The level averages the areas the position needs. Shortlist at a level of 70 or more, Monitor at 50, Not
        now below. Confidence: high at 2,000 minutes, medium at 1,000, low below. Every sentence is a rule over these
        numbers.
        {fromStatsBomb ? " Event data: StatsBomb open data, used under its research and education licence. StatsBomb publishes no dates of birth." : ""}
        {pitch?.xgModel === "northstar"
          ? " Expected goals (xG, npxG, xA) are NorthStar's own model, trained on 37,488 shots and graded against StatsBomb's own xG on three tournaments it never saw."
          : ""}
      </p>
    </div>
  );
}

function Legend({ items }: { items: { colour: string; label: string; filled?: boolean }[] }) {
  return (
    <div className="flex flex-wrap gap-4 text-xs text-slate-300">
      {items.map((i) => (
        <span key={i.label} className="flex items-center gap-2">
          <span
            className="h-3 w-3 rounded-full"
            style={i.filled ? { background: i.colour } : { background: `${i.colour}29`, border: `1px solid ${i.colour}` }}
          />
          {i.label}
        </span>
      ))}
    </div>
  );
}
