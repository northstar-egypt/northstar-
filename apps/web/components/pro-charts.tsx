/**
 * Charts for the professional scouting report (app/(app)/players/[id]/report): a percentile pizza,
 * a shot map, a key-pass map, a touch heat map and a finishing line. Hand-written SVG, like
 * components/charts.tsx. Every mark is drawn from the API's numbers; nothing is smoothed into a
 * value that was not measured, except the heat map's blur, which only softens the grid's edges.
 *
 * Pitch coordinates are the platform's: x from 0 (own goal line) to 100 (the opponent's), y from
 * 0 (left touchline, as the team attacks) to 100. The drawings use StatsBomb's 120 by 80 pitch,
 * which those coordinates come from.
 */

import { useId } from "react";
import type { ReportEvidence } from "@/lib/types";

const PITCH_LINE = "#34496b";
const PITCH_BG_TOP = "#0d1a2e";
const PITCH_BG_BOTTOM = "#0a1424";
export const GOAL = "#fbbf24";
export const CHANCE = "#7dd3fc";

/** One colour per area of the report, in the module's order. */
export const AREA_COLOURS = ["#f59e0b", "#38bdf8", "#a78bfa", "#2dd4bf", "#94a3b8", "#fb7185", "#f472b6", "#a3e635"];

/* ------------------------------------------------------------------ percentile pizza */

function arcPoint(cx: number, cy: number, r: number, degrees: number): [number, number] {
  const a = (degrees * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

function wedge(cx: number, cy: number, r1: number, r2: number, a0: number, a1: number): string {
  const [x1, y1] = arcPoint(cx, cy, r2, a0);
  const [x2, y2] = arcPoint(cx, cy, r2, a1);
  const [x3, y3] = arcPoint(cx, cy, r1, a1);
  const [x4, y4] = arcPoint(cx, cy, r1, a0);
  const f = (n: number) => n.toFixed(1);
  return `M${f(x1)},${f(y1)} A${r2},${r2} 0 0 1 ${f(x2)},${f(y2)} L${f(x3)},${f(y3)} A${r1},${r1} 0 0 0 ${f(x4)},${f(y4)} Z`;
}

export function shortLabel(label: string): string {
  return label.replace(/ per 90$/, "").replace(/^Pass completion$/, "Pass %").replace(/ duels won$/, "s won");
}

export function PercentilePizza({ areas }: { areas: { label: string; evidence: ReportEvidence[] }[] }) {
  const slices = areas.flatMap((area, i) => area.evidence.map((e) => ({ e, colour: AREA_COLOURS[i % AREA_COLOURS.length] })));
  if (slices.length === 0) return null;
  const cx = 300, cy = 300, r0 = 44, R = 210, gap = 1.6;
  const step = 360 / slices.length;
  const at = (p: number) => r0 + ((R - r0) * p) / 100;
  return (
    <svg
      viewBox="-60 50 720 510"
      role="img"
      aria-label={`Percentiles: ${slices.map((s) => `${s.e.label} ${s.e.percentile}`).join(", ")}`}
      className="h-auto w-full"
    >
      {slices.map((s, i) => {
        const a0 = -90 + i * step + gap / 2;
        const a1 = -90 + (i + 1) * step - gap / 2;
        return <path key={`bg-${s.e.key}`} d={wedge(cx, cy, r0, R, a0, a1)} fill="#111a2c" />;
      })}
      {[25, 75, 100].map((f) => (
        <circle key={f} cx={cx} cy={cy} r={at(f)} fill="none" stroke="#22304a" />
      ))}
      <circle cx={cx} cy={cy} r={at(50)} fill="none" stroke="#3a4b6b" strokeDasharray="4 4" />
      {slices.map((s, i) => {
        const a0 = -90 + i * step + gap / 2;
        const a1 = -90 + (i + 1) * step - gap / 2;
        return <path key={s.e.key} d={wedge(cx, cy, r0, at(s.e.percentile), a0, a1)} fill={s.colour} fillOpacity={0.9} />;
      })}
      <circle cx={cx} cy={cy} r={r0 - 4} fill="#0c1322" />
      {slices.map((s, i) => {
        const mid = -90 + (i + 0.5) * step;
        const r = at(s.e.percentile);
        const inside = s.e.percentile >= 30;
        const [x, y] = arcPoint(cx, cy, inside ? Math.max(r - 15, r0 + 15) : r + 14, mid);
        return (
          <text key={`n-${s.e.key}`} x={x} y={y + 4} textAnchor="middle" fontSize={13} fontWeight={700}
            fill={inside ? "#0b1220" : "#e6edf7"} fontFamily="var(--font-plex), monospace">
            {s.e.percentile}
          </text>
        );
      })}
      {slices.map((s, i) => {
        const mid = -90 + (i + 0.5) * step;
        const [x, y] = arcPoint(cx, cy, R + 22, mid);
        const c = Math.cos((mid * Math.PI) / 180);
        const anchor = Math.abs(c) < 0.25 ? "middle" : c > 0 ? "start" : "end";
        return (
          <text key={`l-${s.e.key}`} x={x} y={y + 4} textAnchor={anchor} fontSize={13} fill="#c5d1e3">
            {shortLabel(s.e.label)}
            {s.e.lowReliability ? "*" : ""}
          </text>
        );
      })}
    </svg>
  );
}

/* ------------------------------------------------------------------ pitches */

function Background({ id, x, y, w, h }: { id: string; x: number; y: number; w: number; h: number }) {
  return (
    <>
      <defs>
        <linearGradient id={`${id}-bg`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={PITCH_BG_TOP} />
          <stop offset="1" stopColor={PITCH_BG_BOTTOM} />
        </linearGradient>
      </defs>
      <rect x={x} y={y} width={w} height={h} rx={2} fill={`url(#${id}-bg)`} />
    </>
  );
}

/** The full pitch's lines, attacking to the right. */
function FullPitchLines() {
  return (
    <g fill="none" stroke={PITCH_LINE} strokeWidth={0.4}>
      <rect x={0} y={0} width={120} height={80} />
      <line x1={60} y1={0} x2={60} y2={80} />
      <circle cx={60} cy={40} r={10} />
      <rect x={0} y={18} width={18} height={44} />
      <rect x={102} y={18} width={18} height={44} />
      <rect x={0} y={30} width={6} height={20} />
      <rect x={114} y={30} width={6} height={20} />
      <path d="M18,32.7 A10,10 0 0 1 18,47.3" />
      <path d="M102,32.7 A10,10 0 0 0 102,47.3" />
    </g>
  );
}

export interface ShotMark {
  x: number;
  y: number;
  outcome: string;
  xg: number | null;
}

/** Shots on the attacking end, the goal at the top, as the shooter sees it. Size is xG. */
export function ShotMap({ shots }: { shots: ShotMark[] }) {
  const id = useId().replace(/:/g, "");
  // StatsBomb units: depth from the goal line (0 to 120), across from the left (0 to 80).
  const marks = shots.map((s) => ({ ...s, depth: 120 - (s.x * 120) / 100, across: (s.y * 80) / 100 }));
  const deepest = Math.max(30, ...marks.map((m) => m.depth + 4));
  const depth = Math.min(60, deepest);
  const radius = (xg: number | null) => 0.7 + Math.sqrt(Math.max(0, xg ?? 0.02)) * 3;
  const goals = marks.filter((m) => m.outcome === "goal");
  const misses = marks.filter((m) => m.outcome !== "goal" && m.depth <= depth);
  return (
    <svg viewBox={`-3 -4 86 ${depth + 6}`} role="img" className="h-auto w-full"
      aria-label={`Shot map: ${shots.length} shots, ${goals.length} goals`}>
      <Background id={id} x={-3} y={-4} w={86} h={depth + 6} />
      <g fill="none" stroke={PITCH_LINE} strokeWidth={0.35}>
        <rect x={0} y={0} width={80} height={depth} />
        <rect x={18} y={0} width={44} height={18} />
        <rect x={30} y={0} width={20} height={6} />
        <rect x={36} y={-1.6} width={8} height={1.6} />
        <path d="M32.7,18 A10,10 0 0 0 47.3,18" />
      </g>
      <circle cx={40} cy={12} r={0.35} fill={PITCH_LINE} />
      {misses.map((m, i) => (
        <circle key={`m${i}`} cx={m.across} cy={m.depth} r={radius(m.xg)} fill={CHANCE} fillOpacity={0.16}
          stroke={CHANCE} strokeWidth={0.25} />
      ))}
      {goals.map((m, i) => (
        <circle key={`g${i}`} cx={m.across} cy={m.depth} r={radius(m.xg)} fill={GOAL} stroke="#0b1220" strokeWidth={0.3} />
      ))}
    </svg>
  );
}

export interface PassMark {
  x: number;
  y: number;
  endX: number;
  endY: number;
  outcome: string;
}

/** Passes that led to a shot, attacking to the right; the attacking half unless one started deeper. */
export function KeyPassMap({ passes }: { passes: PassMark[] }) {
  const id = useId().replace(/:/g, "");
  const p = passes.map((k) => ({
    x1: (k.x * 120) / 100, y1: (k.y * 80) / 100, x2: (k.endX * 120) / 100, y2: (k.endY * 80) / 100,
    assist: k.outcome === "assist",
  }));
  const deep = p.some((k) => k.x1 < 58);
  const x0 = deep ? -2 : 58;
  const width = deep ? 124 : 64;
  const ordered = [...p.filter((k) => !k.assist), ...p.filter((k) => k.assist)];
  return (
    <svg viewBox={`${x0} -2 ${width} 84`} role="img" className="h-auto w-full"
      aria-label={`Chances created: ${passes.length} passes that led to a shot, ${p.filter((k) => k.assist).length} assists`}>
      <Background id={id} x={x0} y={-2} w={width} h={84} />
      <FullPitchLines />
      {ordered.map((k, i) => (
        <g key={i}>
          <line x1={k.x1} y1={k.y1} x2={k.x2} y2={k.y2} stroke={k.assist ? GOAL : CHANCE}
            strokeOpacity={k.assist ? 1 : 0.55} strokeWidth={k.assist ? 0.9 : 0.5} />
          <circle cx={k.x2} cy={k.y2} r={k.assist ? 1.3 : 0.8} fill={k.assist ? GOAL : CHANCE} fillOpacity={k.assist ? 1 : 0.7} />
        </g>
      ))}
    </svg>
  );
}

/** Where a player's actions were, from the 12 by 8 touch map, softened at the zone edges. */
export function TouchHeatMap({ grid }: { grid: number[] }) {
  const id = useId().replace(/:/g, "");
  const max = Math.max(1, ...grid);
  const total = grid.reduce((a, b) => a + b, 0);
  return (
    <svg viewBox="-2 -2 124 84" role="img" className="h-auto w-full"
      aria-label={`Heat map of ${total.toLocaleString()} actions with a location`}>
      <Background id={id} x={-2} y={-2} w={124} h={84} />
      <defs>
        <filter id={`${id}-blur`} x="-10%" y="-10%" width="120%" height="120%">
          <feGaussianBlur stdDeviation={3.2} />
        </filter>
        <clipPath id={`${id}-clip`}>
          <rect x={0} y={0} width={120} height={80} />
        </clipPath>
      </defs>
      <g clipPath={`url(#${id}-clip)`}>
        <g filter={`url(#${id}-blur)`}>
          {grid.map((n, i) =>
            n ? (
              <rect key={i} x={(i % 12) * 10} y={Math.floor(i / 12) * 10} width={10} height={10}
                fill="#f59e0b" fillOpacity={0.04 + (n / max) * 0.86} />
            ) : null,
          )}
        </g>
      </g>
      <FullPitchLines />
    </svg>
  );
}

/* ------------------------------------------------------------------ finishing */

/** Goals against the range ordinary finishing gives from the same chances. */
export function FinishingLine({ goals, expected, low, high }: { goals: number; expected: number; low: number; high: number }) {
  const top = Math.max(10, Math.ceil(Math.max(goals, high, expected) / 5) * 5 + 5);
  const X = (v: number) => 30 + (v / top) * 540;
  const ticks = Array.from({ length: top / 5 + 1 }, (_, i) => i * 5);
  return (
    <svg viewBox="0 0 600 84" role="img" className="h-auto w-full"
      aria-label={`Scored ${goals}; expected ${expected}; the usual range is ${low} to ${high}`}>
      <line x1={30} y1={44} x2={570} y2={44} stroke="#2b3a57" strokeWidth={2} />
      <rect x={X(low)} y={34} width={X(high) - X(low)} height={20} rx={4} fill={CHANCE} fillOpacity={0.2}
        stroke={CHANCE} strokeOpacity={0.6} />
      <line x1={X(expected)} y1={28} x2={X(expected)} y2={60} stroke={CHANCE} strokeWidth={2} />
      <circle cx={X(goals)} cy={44} r={9} fill={GOAL} stroke="#0b1220" strokeWidth={2} />
      {ticks.map((t) => (
        <text key={t} x={X(t)} y={78} textAnchor="middle" fontSize={13} fill="#9fb0c8">{t}</text>
      ))}
      <text x={(X(low) + X(high)) / 2} y={20} textAnchor="middle" fontSize={13} fill={CHANCE}>
        usual range {low} to {high}
      </text>
      <text x={X(goals)} y={20} textAnchor="middle" fontSize={13} fontWeight={600} fill={GOAL}>scored {goals}</text>
    </svg>
  );
}
