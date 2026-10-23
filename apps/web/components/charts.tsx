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

  const hasForecast = series.forecast.length > 0;
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
  // The cone's outline: out along the upper edge from the last measurement, then back along the
  // lower edge from the furthest point. Tracing both edges in the same direction would make the
  // polygon cross itself.
  const coneOutline = [
    lastMeasured,
    ...series.forecast.map((f) => ({ date: f.date, value: f.upper })),
    ...[...series.forecast].reverse().map((f) => ({ date: f.date, value: f.lower })),
  ];
  const cone = coneOutline.map((p) => `${x(p.date).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");

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

        {hasForecast ? (
          <>
            <polygon points={cone} fill="#38bdf8" opacity="0.16" />
            <path
              d={line([lastMeasured, ...series.forecast.map((f) => ({ date: f.date, value: f.value }))])}
              fill="none"
              stroke="#38bdf8"
              strokeWidth="1.5"
              strokeDasharray="4 3"
            />
          </>
        ) : null}

        <path d={line(series.measured)} fill="none" stroke="#e2e8f0" strokeWidth="2" />
        {series.measured.map((m) => (
          <circle key={m.date} cx={x(m.date)} cy={y(m.value)} r="2.5" fill="#e2e8f0" />
        ))}

        {/*
          "Today" is the date the forecast was made from. It is not the last measurement: a
          player measured four months ago has four months of cone before today, and marking
          the last measurement as today would hide that.
        */}
        {hasForecast && series.forecastFrom ? (
          <line
            x1={x(series.forecastFrom)}
            x2={x(series.forecastFrom)}
            y1={pad.top}
            y2={height - pad.bottom}
            stroke="#475569"
            strokeWidth="1"
            strokeDasharray="2 3"
          />
        ) : null}

        <text x={pad.left} y={height - 6} fill="#64748b" fontSize="9">
          {shortDate(dates[0])}
        </text>
        {hasForecast && series.forecastFrom ? (
          <text x={x(series.forecastFrom)} y={height - 6} fill="#94a3b8" fontSize="9" textAnchor="middle">
            today
          </text>
        ) : null}
        <text x={width - pad.right} y={height - 6} fill="#64748b" fontSize="9" textAnchor="end">
          {shortDate(dates[dates.length - 1])}
        </text>
      </svg>

      <figcaption className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 bg-slate-200" /> measured
        </span>
        {hasForecast ? (
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-4 bg-sky-400/20" /> forecast, 80% range
          </span>
        ) : null}
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-4 bg-slate-600/60" /> 25th to 75th for their age
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

/**
 * A share with its range, on a fixed scale centred on 50%, so a rating is never drawn without
 * the uncertainty that comes with it. The centre line is an average opponent.
 */
export function ShareRange({
  value,
  low,
  high,
  min = 0.4,
  max = 0.6,
}: {
  value: number;
  low: number;
  high: number;
  min?: number;
  max?: number;
}) {
  const at = (x: number) => `${((Math.min(max, Math.max(min, x)) - min) / (max - min)) * 100}%`;
  const pct = (x: number) => `${Math.round(x * 100)}%`;
  return (
    <div className="flex flex-col gap-1">
      <div
        className="relative h-3 w-full rounded-full bg-slate-800"
        role="img"
        aria-label={`${pct(value)}, range ${pct(low)} to ${pct(high)}`}
      >
        <div className="absolute inset-y-0 left-1/2 w-px bg-slate-600" aria-hidden />
        <div
          className="absolute inset-y-0 rounded-full bg-sky-500/35"
          style={{ left: at(low), width: `calc(${at(high)} - ${at(low)})` }}
          aria-hidden
        />
        <div
          className="absolute -inset-y-0.5 w-1 -translate-x-1/2 rounded-full bg-sky-300"
          style={{ left: at(value) }}
          aria-hidden
        />
      </div>
      <div className="flex justify-between text-[0.65rem] tabular-nums text-slate-600" aria-hidden>
        <span>{pct(min)}</span>
        <span>50%, an average opponent</span>
        <span>{pct(max)}</span>
      </div>
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

export interface RadarSeries {
  name: string;
  /** Axis key -> percentile 1 to 99, or null when there is none. */
  values: Record<string, number | null>;
}

/** Colours for up to three players on one radar. */
export const RADAR_COLOURS = ["#38bdf8", "#f59e0b", "#34d399"];

/**
 * A percentile radar: one spoke per statistic, 0 at the centre and 100 at the edge, one shape
 * per player. An axis with no percentile gets no point and its label says why, so the shape
 * never implies a value that is not known. Rings mark 25, 50 and 75.
 */
export function Radar({
  axes,
  series,
  size = 300,
}: {
  axes: { key: string; label: string }[];
  series: RadarSeries[];
  size?: number;
}) {
  if (axes.length < 3) {
    return <p className="text-sm text-slate-500">Not enough statistics for a radar.</p>;
  }
  const pad = 56;
  const side = 60;
  const c = size / 2;
  const r = c - pad;
  const angle = (i: number) => -Math.PI / 2 + (2 * Math.PI * i) / axes.length;
  const at = (i: number, value: number) => [
    c + Math.cos(angle(i)) * r * (value / 100),
    c + Math.sin(angle(i)) * r * (value / 100),
  ];
  const ring = (value: number) => axes.map((_, i) => at(i, value).join(",")).join(" ");
  const summary = series
    .map(
      (s) =>
        `${s.name}: ` +
        axes
          .map((a) => `${a.label} ${s.values[a.key] == null ? "no percentile" : s.values[a.key]}`)
          .join(", "),
    )
    .join(". ");

  return (
    // Extra room left and right, where the axis labels run outwards.
    <svg
      viewBox={`${-side} 0 ${size + 2 * side} ${size}`}
      className="mx-auto w-full max-w-md"
      role="img"
      aria-label={summary}
    >
      {[25, 50, 75, 100].map((v) => (
        <polygon key={v} points={ring(v)} fill={v === 100 ? "#0f172a" : "none"} stroke="#1e293b" />
      ))}
      {axes.map((a, i) => {
        const [x, y] = at(i, 100);
        const [lx, ly] = at(i, 122);
        const missing = series.every((s) => s.values[a.key] == null);
        return (
          <g key={a.key}>
            <line x1={c} y1={c} x2={x} y2={y} stroke="#1e293b" />
            <text
              x={lx}
              y={ly}
              fill={missing ? "#475569" : "#94a3b8"}
              fontSize="10"
              textAnchor={Math.abs(lx - c) < 8 ? "middle" : lx > c ? "start" : "end"}
              dominantBaseline="middle"
            >
              {a.label}
              {missing ? " (not enough players)" : ""}
            </text>
          </g>
        );
      })}
      {series.map((s, k) => {
        const colour = RADAR_COLOURS[k % RADAR_COLOURS.length];
        const points = axes
          .map((a, i) => (s.values[a.key] == null ? null : at(i, s.values[a.key] as number)))
          .filter((p): p is number[] => p !== null);
        return (
          <g key={s.name}>
            {points.length >= 3 ? (
              <polygon
                points={points.map((p) => p.join(",")).join(" ")}
                fill={colour}
                fillOpacity="0.18"
                stroke={colour}
                strokeWidth="2"
              />
            ) : null}
            {points.map(([x, y], i) => (
              <circle key={i} cx={x} cy={y} r="3.5" fill={colour} />
            ))}
          </g>
        );
      })}
    </svg>
  );
}

/* ------------------------------------------------------------------ scatter */

export interface ScatterDot {
  id: string;
  name: string;
  x: number;
  y: number;
  href: string;
}

/** Round tick values covering [low, high], about `count` of them. */
function niceTicks(low: number, high: number, count = 5): number[] {
  if (high <= low) high = low + 1;
  const raw = (high - low) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? raw;
  // Whole steps from at or below `low` to at or above `high`, so no point falls off the plot.
  const first = Math.floor(low / step);
  const last = Math.ceil(high / step);
  const ticks: number[] = [];
  for (let i = first; i <= last; i++) ticks.push(Number((i * step).toFixed(6)));
  return ticks;
}

/**
 * Players on two statistics. Dashed lines are the group's medians, drawn only when the API
 * sends them (enough players for a median to mean something). Each point links to the
 * player's profile; marked points (the focus player, a name search) are drawn amber and named.
 */
export function ScatterPlot({
  dots,
  xLabel,
  yLabel,
  medians,
  marked,
  width = 640,
  height = 420,
}: {
  dots: ScatterDot[];
  xLabel: string;
  yLabel: string;
  medians: { x: number; y: number } | null;
  marked: Set<string>;
  width?: number;
  height?: number;
}) {
  const pad = { left: 52, right: 16, top: 16, bottom: 44 };
  const xs = dots.map((d) => d.x).concat(medians ? [medians.x] : []);
  const ys = dots.map((d) => d.y).concat(medians ? [medians.y] : []);
  const xTicks = niceTicks(Math.min(0, ...xs), Math.max(...xs, 0.01));
  const yTicks = niceTicks(Math.min(0, ...ys), Math.max(...ys, 0.01));
  const [x0, x1] = [xTicks[0], xTicks[xTicks.length - 1]];
  const [y0, y1] = [yTicks[0], yTicks[yTicks.length - 1]];
  const px = (v: number) => pad.left + ((v - x0) / (x1 - x0 || 1)) * (width - pad.left - pad.right);
  const py = (v: number) => height - pad.bottom - ((v - y0) / (y1 - y0 || 1)) * (height - pad.top - pad.bottom);
  // Marked points last, so they sit on top of the crowd.
  const ordered = [...dots].sort((a, b) => Number(marked.has(a.id)) - Number(marked.has(b.id)));

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full"
      role="img"
      aria-label={`${dots.length} players by ${xLabel} and ${yLabel}`}
    >
      {xTicks.map((t) => (
        <g key={`x${t}`}>
          <line x1={px(t)} x2={px(t)} y1={pad.top} y2={height - pad.bottom} stroke="#1e293b" />
          <text x={px(t)} y={height - pad.bottom + 14} fill="#64748b" fontSize="10" textAnchor="middle">
            {t}
          </text>
        </g>
      ))}
      {yTicks.map((t) => (
        <g key={`y${t}`}>
          <line x1={pad.left} x2={width - pad.right} y1={py(t)} y2={py(t)} stroke="#1e293b" />
          <text x={pad.left - 6} y={py(t)} fill="#64748b" fontSize="10" textAnchor="end" dominantBaseline="middle">
            {t}
          </text>
        </g>
      ))}
      <text x={(pad.left + width - pad.right) / 2} y={height - 8} fill="#94a3b8" fontSize="11" textAnchor="middle">
        {xLabel}
      </text>
      <text
        transform={`translate(12 ${(pad.top + height - pad.bottom) / 2}) rotate(-90)`}
        fill="#94a3b8"
        fontSize="11"
        textAnchor="middle"
      >
        {yLabel}
      </text>
      {medians ? (
        <g stroke="#64748b" strokeDasharray="4 4">
          <line x1={px(medians.x)} x2={px(medians.x)} y1={pad.top} y2={height - pad.bottom} />
          <line x1={pad.left} x2={width - pad.right} y1={py(medians.y)} y2={py(medians.y)} />
        </g>
      ) : null}
      {ordered.map((d) => {
        const on = marked.has(d.id);
        return (
          <a key={d.id} href={d.href} aria-label={`${d.name}: ${d.x}, ${d.y}`}>
            <circle
              cx={px(d.x)}
              cy={py(d.y)}
              r={on ? 6 : 4}
              fill={on ? "#f59e0b" : "#38bdf8"}
              fillOpacity={on ? 1 : 0.6}
              stroke={on ? "#fde68a" : "none"}
            >
              <title>{`${d.name}\n${xLabel}: ${d.x}\n${yLabel}: ${d.y}`}</title>
            </circle>
            {on ? (
              <text
                x={px(d.x) + (px(d.x) > width - 140 ? -9 : 9)}
                y={py(d.y) - 8}
                fill="#fde68a"
                fontSize="11"
                textAnchor={px(d.x) > width - 140 ? "end" : "start"}
              >
                {d.name}
              </text>
            ) : null}
          </a>
        );
      })}
    </svg>
  );
}

/* ------------------------------------------------------------------ pitch */

export interface PitchMarker {
  id: string;
  /** 0 to 100, own goal line to the opponent's. */
  x: number;
  /** 0 to 100, left touchline to right, as the team attacks. */
  y: number;
  colour: string;
  /** Read out and shown on hover. */
  label: string;
  /** Drawn larger and outlined, for the one being worked on. */
  selected?: boolean;
}

/**
 * A football pitch, attacking to the right, 105 by 68 metres at 5 units a metre, so the boxes
 * and the circle are true to scale. `half` shows only the attacking half (a shot map).
 * `onPick` makes it clickable and reports where, on the same 0 to 100 scale the events use.
 */
export function Pitch({
  markers,
  half = false,
  onPick,
}: {
  markers: PitchMarker[];
  half?: boolean;
  onPick?: (x: number, y: number) => void;
}) {
  const W = 525;
  const H = 340;
  const m = 5; // units per metre
  const box = { depth: 16.5 * m, top: (H - 40.32 * m) / 2, height: 40.32 * m };
  const six = { depth: 5.5 * m, top: (H - 18.32 * m) / 2, height: 18.32 * m };
  const goal = { top: (H - 7.32 * m) / 2, height: 7.32 * m };
  const left = half ? W / 2 : 0;
  const line = { stroke: "#334155", strokeWidth: 2, fill: "none" };

  const pick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!onPick) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const width = half ? W / 2 : W;
    const sx = left + ((e.clientX - rect.left) / rect.width) * width;
    const sy = ((e.clientY - rect.top) / rect.height) * H;
    const round = (v: number) => Math.round(Math.min(100, Math.max(0, v)) * 10) / 10;
    onPick(round((sx / W) * 100), round((sy / H) * 100));
  };

  return (
    <svg
      viewBox={`${left} 0 ${half ? W / 2 : W} ${H}`}
      className={onPick ? "w-full cursor-crosshair touch-none select-none" : "w-full"}
      role="img"
      aria-label={`Pitch with ${markers.length} marked events`}
      onClick={pick}
    >
      <rect x={0} y={0} width={W} height={H} fill="#0b1f17" />
      <rect x={2} y={2} width={W - 4} height={H - 4} {...line} />
      <line x1={W / 2} y1={2} x2={W / 2} y2={H - 2} {...line} />
      <circle cx={W / 2} cy={H / 2} r={9.15 * m} {...line} />
      <circle cx={W / 2} cy={H / 2} r={2} fill="#334155" />
      {[0, 1].map((side) => {
        // Distance d metres-in-units from this side's goal line.
        const at = (d: number) => (side === 0 ? 2 + d : W - 2 - d);
        return (
          <g key={side}>
            <rect x={side === 0 ? 2 : W - 2 - box.depth} y={box.top} width={box.depth} height={box.height} {...line} />
            <rect x={side === 0 ? 2 : W - 2 - six.depth} y={six.top} width={six.depth} height={six.height} {...line} />
            <circle cx={at(11 * m)} cy={H / 2} r={2} fill="#334155" />
            <line x1={at(0)} y1={goal.top} x2={at(0)} y2={goal.top + goal.height} stroke="#94a3b8" strokeWidth={4} />
          </g>
        );
      })}
      {markers.map((mk) => (
        <circle
          key={mk.id}
          cx={(mk.x / 100) * W}
          cy={(mk.y / 100) * H}
          r={mk.selected ? 8 : 6}
          fill={mk.colour}
          fillOpacity={0.85}
          stroke={mk.selected ? "#f8fafc" : "#0f172a"}
          strokeWidth={mk.selected ? 2.5 : 1}
        >
          <title>{mk.label}</title>
        </circle>
      ))}
    </svg>
  );
}

/* ------------------------------------------------------------------ table tennis table */

/**
 * A table tennis table seen from above, 2.74 by 1.525 metres to scale, the player's own end on
 * the left and the opponent's on the right. Markers and `onPick` use the same 0 to 100 scale as
 * the pitch: x from the player's own end to the opponent's, y across the table.
 */
export function TennisTable({
  markers,
  onPick,
}: {
  markers: PitchMarker[];
  onPick?: (x: number, y: number) => void;
}) {
  const W = 274;
  const H = 152.5;
  const pad = 14;
  const line = { stroke: "#e2e8f0", strokeWidth: 1.2, fill: "none" };

  const pick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!onPick) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const sx = ((e.clientX - rect.left) / rect.width) * (W + 2 * pad) - pad;
    const sy = ((e.clientY - rect.top) / rect.height) * (H + 2 * pad) - pad;
    const round = (v: number) => Math.round(Math.min(100, Math.max(0, v)) * 10) / 10;
    onPick(round((sx / W) * 100), round((sy / H) * 100));
  };

  return (
    <svg
      viewBox={`${-pad} ${-pad} ${W + 2 * pad} ${H + 2 * pad + 10}`}
      className={onPick ? "w-full cursor-crosshair touch-none select-none" : "w-full"}
      role="img"
      aria-label={`Table with ${markers.length} marked points`}
      onClick={pick}
    >
      <rect x={0} y={0} width={W} height={H} fill="#1e3a5f" />
      <rect x={0} y={0} width={W} height={H} {...line} />
      {/* The centre line, for doubles, and the net. */}
      <line x1={0} y1={H / 2} x2={W} y2={H / 2} stroke="#e2e8f0" strokeWidth={0.6} strokeOpacity={0.6} />
      <line x1={W / 2} y1={-6} x2={W / 2} y2={H + 6} stroke="#f8fafc" strokeWidth={2.5} />
      <text x={W / 4} y={H + pad + 4} fill="#94a3b8" fontSize="9" textAnchor="middle">
        own side
      </text>
      <text x={(3 * W) / 4} y={H + pad + 4} fill="#94a3b8" fontSize="9" textAnchor="middle">
        opponent&apos;s side
      </text>
      {markers.map((mk) => (
        <circle
          key={mk.id}
          cx={(mk.x / 100) * W}
          cy={(mk.y / 100) * H}
          r={mk.selected ? 4.5 : 3.2}
          fill={mk.colour}
          fillOpacity={0.85}
          stroke={mk.selected ? "#f8fafc" : "#0f172a"}
          strokeWidth={mk.selected ? 1.5 : 0.6}
        >
          <title>{mk.label}</title>
        </circle>
      ))}
    </svg>
  );
}
