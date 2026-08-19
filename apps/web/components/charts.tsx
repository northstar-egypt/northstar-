/**
 * Charts, hand written as SVG.
 *
 * CLAUDE.md names Recharts in the stack, but it is not installed and adding it is a new core
 * dependency, which the same file says to ask about first. These four charts are what the
 * screens need, they are small, and they have no dependencies. If the team decides on Recharts,
 * these are the spec for what to build with it.
 *
 * The one rule that matters here: a forecast is drawn as a widening band, never as a bare line.
 * A line implies a confidence the model does not have, and the whole product argument rests on
 * showing uncertainty rather than hiding it.
 */

import type { GrowthSeries } from "@/lib/types";
import { ordinal, shortDate } from "@/lib/format";

/* ------------------------------------------------------------------ sparkline */

export function Sparkline({
  values,
  width = 72,
  height = 22,
}: {
  values: number[];
  width?: number;
  height?: number;
}) {
  if (values.length < 2) {
    return <span className="text-xs text-slate-600">no trend</span>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = width / (values.length - 1);
  const points = values
    .map((v, i) => `${(i * step).toFixed(1)},${(height - ((v - min) / span) * height).toFixed(1)}`)
    .join(" ");

  const flat = span < 1;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`Trend from ${values[0]} to ${values[values.length - 1]}`}
      className="overflow-visible"
    >
      <polyline
        points={points}
        fill="none"
        stroke={flat ? "#f59e0b" : "#38bdf8"}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle
        cx={width}
        cy={height - ((values[values.length - 1] - min) / span) * height}
        r="2"
        fill={flat ? "#f59e0b" : "#38bdf8"}
      />
    </svg>
  );
}

/* ------------------------------------------------------------------ growth curve */

/**
 * The player's measured history, the population band behind it, and the forecast ahead of it
 * drawn as a cone. Three layers, one frame, because the comparison between them is the point.
 */
export function GrowthChart({ series, height = 220 }: { series: GrowthSeries; height?: number }) {
  const width = 640;
  const pad = { top: 12, right: 14, bottom: 24, left: 34 };

  const all = [
    ...series.measured.map((m) => m.value),
    ...series.forecast.map((f) => f.upper),
    ...series.forecast.map((f) => f.lower),
    ...series.population.map((p) => p.p25),
    ...series.population.map((p) => p.p75),
  ];
  const min = Math.floor(Math.min(...all) - 2);
  const max = Math.ceil(Math.max(...all) + 2);

  const dates = [...series.measured.map((m) => m.date), ...series.forecast.map((f) => f.date)];
  const t0 = new Date(dates[0]).getTime();
  const t1 = new Date(dates[dates.length - 1]).getTime();

  const x = (iso: string) =>
    pad.left + ((new Date(iso).getTime() - t0) / (t1 - t0 || 1)) * (width - pad.left - pad.right);
  const y = (v: number) =>
    pad.top + (1 - (v - min) / (max - min || 1)) * (height - pad.top - pad.bottom);

  const line = (pts: { date: string; value: number }[]) =>
    pts.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.date).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");

  const popBand =
    series.population.map((p) => `${x(p.date).toFixed(1)},${y(p.p75).toFixed(1)}`).join(" ") +
    " " +
    [...series.population].reverse().map((p) => `${x(p.date).toFixed(1)},${y(p.p25).toFixed(1)}`).join(" ");

  const lastMeasured = series.measured[series.measured.length - 1];
  const coneTop = [lastMeasured, ...series.forecast.map((f) => ({ date: f.date, value: f.upper }))];
  const coneBottom = [
    ...series.forecast.map((f) => ({ date: f.date, value: f.lower })),
    lastMeasured,
  ].reverse();
  const cone =
    coneTop.map((p) => `${x(p.date).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ") +
    " " +
    coneBottom.reverse().map((p) => `${x(p.date).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");

  const ticks = [min, Math.round((min + max) / 2), max];

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="img"
        aria-label={`Height over time in ${series.unit}, with a population band and a forecast band`}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={pad.left}
              x2={width - pad.right}
              y1={y(t)}
              y2={y(t)}
              stroke="#1e293b"
              strokeWidth="1"
            />
            <text x={4} y={y(t) + 3} fill="#64748b" fontSize="9">
              {t}
            </text>
          </g>
        ))}

        <polygon points={popBand} fill="#334155" opacity="0.45" />

        <polygon points={cone} fill="#38bdf8" opacity="0.16" />
        <path
          d={line([lastMeasured, ...series.forecast.map((f) => ({ date: f.date, value: f.value }))])}
          fill="none"
          stroke="#38bdf8"
          strokeWidth="1.5"
          strokeDasharray="4 3"
        />

        <path d={line(series.measured)} fill="none" stroke="#e2e8f0" strokeWidth="2" />
        {series.measured.map((m) => (
          <circle key={m.date} cx={x(m.date)} cy={y(m.value)} r="2.5" fill="#e2e8f0" />
        ))}

        <line
          x1={x(lastMeasured.date)}
          x2={x(lastMeasured.date)}
          y1={pad.top}
          y2={height - pad.bottom}
          stroke="#475569"
          strokeWidth="1"
          strokeDasharray="2 3"
        />

        <text x={pad.left} y={height - 6} fill="#64748b" fontSize="9">
          {shortDate(dates[0])}
        </text>
        <text x={x(lastMeasured.date)} y={height - 6} fill="#94a3b8" fontSize="9" textAnchor="middle">
          today
        </text>
        <text x={width - pad.right} y={height - 6} fill="#64748b" fontSize="9" textAnchor="end">
          {shortDate(dates[dates.length - 1])}
        </text>
      </svg>

      <figcaption className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 bg-slate-200" /> measured
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-4 bg-sky-400/20" /> forecast range
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-4 bg-slate-600/60" /> 25th to 75th for his age
        </span>
      </figcaption>
    </figure>
  );
}

/* ------------------------------------------------------------------ percentile bar */

export function PercentileBar({
  percentile,
  higherIsBetter,
}: {
  percentile: number;
  higherIsBetter: boolean;
}) {
  const strong = higherIsBetter ? percentile >= 70 : percentile <= 30;
  const weak = higherIsBetter ? percentile <= 30 : percentile >= 70;
  const color = strong ? "bg-emerald-500" : weak ? "bg-amber-500" : "bg-slate-500";

  return (
    <div
      className="relative h-2 w-full overflow-hidden rounded-full bg-slate-800"
      role="img"
      aria-label={`${ordinal(percentile)} percentile`}
    >
      <div className={`h-full ${color}`} style={{ width: `${Math.max(2, percentile)}%` }} />
      <div className="absolute inset-y-0 left-1/2 w-px bg-slate-600" aria-hidden />
    </div>
  );
}

/* ------------------------------------------------------------------ horizontal bars */

/**
 * Used for coverage by region. Takes a value and a reference so the bar can show players per
 * million rather than a raw total, which is the whole point of that panel.
 */
export function RatioBars({
  rows,
}: {
  rows: { label: string; value: number; per: number }[];
}) {
  const max = Math.max(...rows.map((r) => r.value / r.per));
  return (
    <ul className="flex flex-col gap-2">
      {rows.map((r) => {
        const ratio = r.value / r.per;
        const share = (ratio / max) * 100;
        const thin = share < 22;
        return (
          <li key={r.label} className="grid grid-cols-[6rem_1fr_5rem] items-center gap-3 text-xs">
            <span className="truncate text-slate-400">{r.label}</span>
            <div className="h-3 w-full rounded-sm bg-slate-800">
              <div
                className={thin ? "h-full rounded-sm bg-amber-500/80" : "h-full rounded-sm bg-sky-500/80"}
                style={{ width: `${Math.max(1.5, share)}%` }}
              />
            </div>
            <span className="text-right tabular-nums text-slate-400">
              {ratio.toFixed(0)} per M
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/* ------------------------------------------------------------------ stacked columns */

export function StackedAges({
  rows,
}: {
  rows: { age: number; pro: number; youth: number; diaspora: number }[];
}) {
  const max = Math.max(...rows.map((r) => r.pro + r.youth + r.diaspora));
  return (
    <div>
      <div className="flex h-40 items-end gap-2">
        {rows.map((r) => {
          const total = r.pro + r.youth + r.diaspora;
          return (
            <div key={r.age} className="flex flex-1 flex-col items-center gap-1">
              <div
                className="flex w-full flex-col-reverse justify-start"
                style={{ height: `${(total / max) * 100}%` }}
                title={`age ${r.age}: ${total} players`}
              >
                <div className="w-full bg-sky-500/80" style={{ height: `${(r.youth / total) * 100}%` }} />
                <div className="w-full bg-emerald-500/80" style={{ height: `${(r.pro / total) * 100}%` }} />
                <div className="w-full bg-amber-500/80" style={{ height: `${(r.diaspora / total) * 100}%` }} />
              </div>
              <span className="text-[0.65rem] tabular-nums text-slate-500">{r.age}</span>
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
        <span className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 bg-sky-500/80" /> youth</span>
        <span className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 bg-emerald-500/80" /> pro</span>
        <span className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 bg-amber-500/80" /> diaspora</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ overlaid growth */

export function OverlaidGrowth({
  series,
  labels,
}: {
  series: { playerId: string; points: { date: string; value: number }[] }[];
  labels: string[];
}) {
  const width = 520;
  const height = 180;
  const pad = { top: 10, right: 12, bottom: 20, left: 30 };
  const colors = ["#38bdf8", "#f59e0b", "#a78bfa"];

  const all = series.flatMap((s) => s.points.map((p) => p.value));
  const min = Math.floor(Math.min(...all) - 2);
  const max = Math.ceil(Math.max(...all) + 2);
  const dates = series[0]?.points.map((p) => new Date(p.date).getTime()) ?? [];
  const t0 = Math.min(...dates);
  const t1 = Math.max(...dates);

  const x = (iso: string) =>
    pad.left + ((new Date(iso).getTime() - t0) / (t1 - t0 || 1)) * (width - pad.left - pad.right);
  const y = (v: number) =>
    pad.top + (1 - (v - min) / (max - min || 1)) * (height - pad.top - pad.bottom);

  return (
    <figure className="m-0">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="Growth curves compared">
        {[min, max].map((t) => (
          <g key={t}>
            <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} stroke="#1e293b" />
            <text x={2} y={y(t) + 3} fill="#64748b" fontSize="9">{t}</text>
          </g>
        ))}
        {series.map((s, i) => (
          <path
            key={s.playerId}
            d={s.points.map((p, j) => `${j === 0 ? "M" : "L"}${x(p.date).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ")}
            fill="none"
            stroke={colors[i % colors.length]}
            strokeWidth="2"
          />
        ))}
      </svg>
      <figcaption className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
        {labels.map((l, i) => (
          <span key={l} className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4" style={{ background: colors[i % colors.length] }} />
            {l}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
