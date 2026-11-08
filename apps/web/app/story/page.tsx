"use client";

/**
 * "The ones we'd have let go": the project's argument in one screen, and the demo's opening.
 *
 * One boy from the synthetic dataset, chosen by a fixed rule rather than by eye (ml/figure_late_
 * bloomer.py): small enough at about 14 to fall in the shortest quarter of his age group, the day a
 * size-based cut would have released him, what NorthStar said that same day, and how tall he went
 * on to be. Then the pattern across five datasets, from the late-bloomer backtest (ml/README.md).
 *
 * The data is the figure's own (public/story/late-bloomer.sample.json, written by
 * `python -m ml.figure_late_bloomer`), so this screen cannot drift from the graded numbers. It is
 * public: the story needs no account, and holds no real person.
 */

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

interface Story {
  seed: number;
  sample: string;
  player: { name: string; position: string | null; sex: string };
  readings: { age: number; cm: number; known: boolean }[];
  curve: { age: number; cm: number }[];
  band: { age: number; median: number; spread: number }[];
  cut: { age: number; heightZ: number; readings: number; flagged: boolean; reason: string };
  adult: { heightCm: number; medianCm: number | null; age: number };
  maturityOffsetYears: number;
  endAge: number;
  rates: {
    minReadings: number;
    caughtWithHistory: Rate;
    otherSmallWithHistory: Rate;
    caughtWithoutHistory: Rate;
  };
}
interface Rate {
  hits: number;
  total: number;
  low: number;
  high: number;
}

const W = 860;
const H = 440;
const PAD = { left: 56, right: 24, top: 40, bottom: 44 };
const pct = (x: number) => `${Math.round(x * 100)}%`;
const share = (r: Rate) => (r.total ? r.hits / r.total : 0);

export default function StoryPage() {
  const [story, setStory] = useState<Story | null>(null);
  const [failed, setFailed] = useState(false);
  const [age, setAge] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const frame = useRef<number | null>(null);

  useEffect(() => {
    fetch("/story/late-bloomer.sample.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((s: Story) => {
        setStory(s);
        setAge(s.readings[0].age);
      })
      .catch(() => setFailed(true));
  }, []);

  const startAge = story ? Math.floor(Math.min(story.readings[0].age, story.band[0]?.age ?? 99)) : 0;
  const endAge = story?.endAge ?? 20;

  // Playing walks the slider from where it is to the end, about four seconds a decade.
  useEffect(() => {
    if (!playing || age == null) return;
    let last = performance.now();
    const step = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      setAge((a) => {
        const next = Math.min(endAge, (a ?? startAge) + dt * 2.2);
        if (next >= endAge) setPlaying(false);
        return next;
      });
      frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing]);

  const scale = useMemo(() => {
    if (!story) return null;
    const heights = [
      ...story.readings.map((r) => r.cm),
      ...story.curve.map((c) => c.cm),
      ...story.band.flatMap((b) => [b.median - b.spread, b.median + b.spread]),
    ];
    const y0 = Math.floor(Math.min(...heights) / 10) * 10;
    const y1 = Math.ceil(Math.max(...heights) / 10) * 10;
    const x = (a: number) => PAD.left + ((a - startAge) / (endAge - startAge)) * (W - PAD.left - PAD.right);
    const y = (cm: number) => PAD.top + (1 - (cm - y0) / (y1 - y0)) * (H - PAD.top - PAD.bottom);
    return { x, y, y0, y1 };
  }, [story, startAge, endAge]);

  if (failed) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-16 text-slate-300">
        The story&apos;s data is missing. Run <code>python -m ml.figure_late_bloomer</code> to write it.
      </main>
    );
  }
  if (!story || !scale || age == null) {
    return <main className="min-h-screen bg-slate-950" />;
  }

  const { x, y, y0, y1 } = scale;
  const cut = story.cut;
  const stage = age < cut.age - 0.05 ? "before" : age < cut.age + 1.2 ? "cut" : "after";
  const shown = story.readings.filter((r) => r.age <= age);
  const curveShown = story.curve.filter((c) => c.age <= age);
  const firstName = story.player.name.split(" ")[0];
  const bandPath = [
    ...story.band.map((b) => `${x(b.age)},${y(b.median + b.spread)}`),
    ...[...story.band].reverse().map((b) => `${x(b.age)},${y(b.median - b.spread)}`),
  ].join(" ");
  const yTicks = Array.from({ length: Math.round((y1 - y0) / 10) + 1 }, (_, i) => y0 + i * 10);
  const xTicks = Array.from({ length: Math.floor(endAge) - Math.ceil(startAge) + 1 }, (_, i) => Math.ceil(startAge) + i);
  const r = story.rates;

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto flex max-w-5xl flex-col gap-10 px-4 py-10 sm:py-16">
        <header className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-2 font-bold tracking-tight">
            <span className="inline-block h-2.5 w-2.5 rotate-45 bg-sky-400" aria-hidden />
            NorthStar
          </span>
          <Link href="/login" className="text-sm text-sky-300 hover:underline">
            Sign in
          </Link>
        </header>

        <section className="max-w-3xl">
          <p className="text-sm font-medium uppercase tracking-widest text-amber-400">The ones we&apos;d have let go</p>
          <h1 className="mt-3 text-4xl font-bold leading-tight tracking-tight sm:text-5xl">
            At {Math.floor(cut.age)}, {firstName} was one of the smallest boys his age.
          </h1>
          <p className="mt-4 text-lg text-slate-400">
            Most academies cut players like him. Here is what happened next, and what NorthStar saw on the day.
          </p>
        </section>

        <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4 sm:p-6">
          <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`Height of ${story.player.name} by age, against his age group`}>
            {yTicks.map((t) => (
              <g key={t}>
                <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} stroke="#1e293b" />
                <text x={PAD.left - 10} y={y(t) + 4} textAnchor="end" fontSize="12" fill="#64748b">
                  {t}
                </text>
              </g>
            ))}
            {xTicks.map((t) => (
              <text key={t} x={x(t)} y={H - PAD.bottom + 22} textAnchor="middle" fontSize="12" fill="#64748b">
                {t}
              </text>
            ))}
            <text x={W - PAD.right} y={H - 6} textAnchor="end" fontSize="12" fill="#64748b">
              age
            </text>
            <text x={PAD.left - 10} y={PAD.top - 16} textAnchor="end" fontSize="12" fill="#64748b">
              cm
            </text>

            <polygon points={bandPath} fill="#334155" opacity="0.55" />
            <polyline
              points={story.band.map((b) => `${x(b.age)},${y(b.median)}`).join(" ")}
              fill="none"
              stroke="#64748b"
              strokeDasharray="2 4"
            />

            {age >= cut.age - 0.05 ? (
              <g>
                <line x1={x(cut.age)} x2={x(cut.age)} y1={PAD.top} y2={H - PAD.bottom} stroke="#f87171" strokeWidth="2" />
                <text x={x(cut.age) + 8} y={PAD.top + 16} fontSize="13" fill="#fca5a5" fontWeight="600">
                  the cut
                </text>
              </g>
            ) : null}

            {curveShown.length > 1 ? (
              <polyline
                points={curveShown.map((c) => `${x(c.age)},${y(c.cm)}`).join(" ")}
                fill="none"
                stroke="#34d399"
                strokeWidth="2.5"
                strokeDasharray="6 5"
              />
            ) : null}
            <polyline
              points={shown.map((p) => `${x(p.age)},${y(p.cm)}`).join(" ")}
              fill="none"
              stroke="#38bdf8"
              strokeWidth="2.5"
            />
            {shown.map((p) => (
              <circle
                key={p.age}
                cx={x(p.age)}
                cy={y(p.cm)}
                r="4.5"
                fill={p.known ? "#38bdf8" : "#020617"}
                stroke="#38bdf8"
                strokeWidth="2"
              />
            ))}
          </svg>

          <div className="mt-4 flex flex-wrap items-center gap-4">
            <button
              type="button"
              onClick={() => {
                if (age >= endAge) setAge(startAge);
                setPlaying((p) => !p);
              }}
              className="rounded-full bg-sky-500 px-5 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-400"
            >
              {playing ? "Pause" : age >= endAge ? "Play again" : "Play"}
            </button>
            <input
              type="range"
              min={startAge}
              max={endAge}
              step={0.05}
              value={age}
              onChange={(e) => {
                setPlaying(false);
                setAge(Number(e.target.value));
              }}
              aria-label="Age"
              className="min-w-[12rem] flex-1 accent-sky-400"
            />
            <span className="w-20 text-right text-lg font-semibold tabular-nums">age {age.toFixed(1)}</span>
          </div>
          <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-500">
            <span className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-full bg-sky-400" /> measured</span>
            <span className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-full border-2 border-sky-400" /> measured after the cut</span>
            <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 border-t-2 border-dashed border-emerald-400" /> how he went on to grow</span>
            <span className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-4 bg-slate-600" /> boys his age, middle two thirds</span>
          </div>
        </section>

        {/* The three beats follow the slider. */}
        <section className="grid gap-4 md:grid-cols-3">
          <Beat active={stage === "before"} label="Before">
            Small for his age, and still growing. {cut.readings} height readings by the day of the cut. A coach looking at
            the squad sees one of the shortest boys.
          </Beat>
          <Beat active={stage === "cut"} label={`The cut, at ${cut.age.toFixed(1)}`} tone="cut">
            In the shortest quarter of boys aged 12 to 16. A size-based cut releases him.
            {cut.flagged ? (
              <span className="mt-3 block rounded-lg border border-sky-500/40 bg-sky-500/10 p-3 text-sky-100">
                <span className="block text-xs font-semibold uppercase tracking-wide text-sky-300">NorthStar, the same day</span>
                {cut.reason}
              </span>
            ) : null}
          </Beat>
          <Beat active={stage === "after"} label="After" tone="after">
            He kept growing. At {Math.floor(cut.age)} he was {Math.abs(cut.heightZ).toFixed(1)} standard deviations below boys
            his age; fully grown he stands {story.adult.heightCm} cm
            {story.adult.medianCm != null
              ? story.adult.heightCm >= story.adult.medianCm
                ? `, taller than the median man at ${story.adult.age} (${story.adult.medianCm} cm)`
                : `, ${(story.adult.medianCm - story.adult.heightCm).toFixed(1)} cm from the median man at ${story.adult.age}: an ordinary adult height`
              : ""}
            . He was behind in growth, not in ability.
          </Beat>
        </section>

        <section className="flex flex-col gap-6">
          <div className="max-w-3xl">
            <p className="text-sm font-medium uppercase tracking-widest text-sky-400">Not one boy. The pattern.</p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight">
              Go back to the day a size cut would have released them, and ask what NorthStar said.
            </h2>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <Stat
              big={pct(share(r.caughtWithHistory))}
              tone="text-emerald-300"
              title="of late bloomers flagged on the day"
              detail={`${r.caughtWithHistory.hits} of ${r.caughtWithHistory.total} measured ${r.minReadings} or more times (95% range ${pct(r.caughtWithHistory.low)} to ${pct(r.caughtWithHistory.high)})`}
            />
            <Stat
              big={pct(share(r.otherSmallWithHistory))}
              tone="text-slate-200"
              title="of other small boys flagged"
              detail={`${r.otherSmallWithHistory.hits} of ${r.otherSmallWithHistory.total}: boys who were simply small, measured as often`}
            />
            <Stat
              big={pct(share(r.caughtWithoutHistory))}
              tone="text-amber-300"
              title="of late bloomers measured too rarely were flagged"
              detail={`${r.caughtWithoutHistory.hits} of ${r.caughtWithoutHistory.total} measured fewer than ${r.minReadings} times. No model can see growth in one reading.`}
            />
          </div>
          <div className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-6">
            <p className="text-2xl font-semibold leading-snug">
              The fix is not a better model. It is a tape measure: at intake, and every few months after.
            </p>
            <p className="mt-2 text-slate-400">
              That is why the coach&apos;s home opens on measuring day.
            </p>
          </div>
        </section>

        <footer className="flex flex-col gap-3 border-t border-slate-800 pt-6 text-sm text-slate-500">
          <p>
            {story.player.name} is not a real person. He comes from NorthStar&apos;s synthetic dataset (seed {story.seed}), and
            he was chosen by a fixed rule, not by eye: of the planted late bloomers the cut reached and the system
            flagged, the one closest to 14. About {pct(share(r.caughtWithHistory))} of such boys are flagged, not all. The
            line after his last reading is the growth his record was generated from, which a real deployment would not
            know in advance. The pattern is from the late-bloomer backtest over {story.sample}.
          </p>
          <div className="flex flex-wrap gap-4">
            <Link href="/login" className="text-sky-300 hover:underline">
              Sign in to NorthStar
            </Link>
          </div>
        </footer>
      </div>
    </main>
  );
}

function Beat({
  active,
  label,
  tone,
  children,
}: {
  active: boolean;
  label: string;
  tone?: "cut" | "after";
  children: React.ReactNode;
}) {
  const accent = tone === "cut" ? "border-red-400/60" : tone === "after" ? "border-emerald-400/60" : "border-sky-400/60";
  return (
    <div
      className={`rounded-2xl border p-5 text-slate-300 transition-opacity duration-300 ${
        active ? `${accent} bg-slate-900 opacity-100` : "border-slate-800 bg-slate-900/40 opacity-50"
      }`}
    >
      <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-slate-400">{label}</p>
      <p className="leading-relaxed">{children}</p>
    </div>
  );
}

function Stat({ big, tone, title, detail }: { big: string; tone: string; title: string; detail: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-6">
      <p className={`text-6xl font-bold tabular-nums ${tone}`}>{big}</p>
      <p className="mt-2 text-lg font-semibold text-slate-100">{title}</p>
      <p className="mt-1 text-sm text-slate-500">{detail}</p>
    </div>
  );
}
