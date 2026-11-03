"use client";

/**
 * The coach's home. See docs/wireframes/02-coach-dashboard.html.
 *
 * The screen answers one question on arrival: who needs my attention today. So it opens with
 * measuring day, the players due a reading, each with a box to log their height right there:
 * a coach at the pitch side with a phone should not have to open twenty profiles. Then the
 * good news (who is growing fastest, who the models think is a late bloomer), then the squad.
 *
 * Nothing on it is computed here. The growth rate comes from the API, which gives none for an
 * adult or without two readings six months apart; the flags are the detectors' own.
 */

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Sparkline } from "@/components/charts";
import {
  Avatar,
  Button,
  Card,
  Chip,
  Empty,
  SectionTitle,
  Skeleton,
  Stat,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { getSquad, logMeasurement, writeRefusal, type MeasurementWarning } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { STALE_DAYS, cx, daysLabel, flagsByType, isStale, times } from "@/lib/format";
import { ROLE_IDENTITY } from "@/lib/roles";
import type { SquadRow } from "@/lib/types";

const coach = ROLE_IDENTITY.coach;

type Filter = "all" | "overdue" | "consent" | "flagged" | "readings";

export default function DashboardPage() {
  const { user } = useAuth();
  const [rows, setRows] = useState<SquadRow[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  // Bumped after a reading is saved, so the squad's numbers catch up.
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let alive = true;
    getSquad().then((r) => alive && setRows(r));
    return () => {
      alive = false;
    };
  }, [version]);

  const counts = useMemo(() => {
    if (!rows) return { overdue: 0, consent: 0, flagged: 0, readings: 0 };
    return {
      overdue: rows.filter((r) => isStale(r.daysSinceLastLog)).length,
      consent: rows.filter((r) => !r.consentComplete).length,
      flagged: rows.filter((r) => r.flags.some((f) => f.type !== "consent")).length,
      readings: rows.filter((r) => r.heightReadingsNeeded > 0).length,
    };
  }, [rows]);

  const visible = useMemo(() => {
    if (!rows) return [];
    const filtered = rows.filter((r) => {
      if (filter === "overdue") return isStale(r.daysSinceLastLog);
      if (filter === "consent") return !r.consentComplete;
      if (filter === "flagged") return r.flags.some((f) => f.type !== "consent");
      if (filter === "readings") return r.heightReadingsNeeded > 0;
      return true;
    });
    // Attention first: the stalest records at the top, because this is a work queue.
    return [...filtered].sort((a, b) => (b.daysSinceLastLog ?? 9999) - (a.daysSinceLastLog ?? 9999));
  }, [rows, filter]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className={cx("text-3xl font-bold tracking-tight", coach.text)}>
            {coach.greeting(user?.fullName?.split(" ")[0] ?? null)}
          </h1>
          <p className="mt-1 text-slate-400">{coach.tagline}</p>
          <p className="text-sm text-slate-500">
            {user?.organizationName}
            {rows ? `, ${rows.length} players` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/compare">
            <Button variant="ghost">Compare players</Button>
          </Link>
          <Link href="/players/import">
            <Button variant="ghost">Import from spreadsheet</Button>
          </Link>
          <Link href="/matches/tag">
            <Button variant="ghost">Tag a match</Button>
          </Link>
          <Link href="/players/new">
            <Button variant="primary">Add player</Button>
          </Link>
        </div>
      </div>

      {rows ? <MeasuringDay rows={rows} onSaved={() => setVersion((v) => v + 1)} /> : null}

      {rows ? (
        <div className="grid gap-5 md:grid-cols-2">
          <Growing rows={rows} />
          <Noticed rows={rows} />
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {rows ? (
          <>
            <Stat label="Squad size" value={rows.length} />
            <Stat
              label={`Not measured in ${STALE_DAYS} days`}
              value={counts.overdue}
              tone={counts.overdue > 0 ? "warn" : "good"}
              hint="listed first below"
            />
            <Stat
              label="Consent missing"
              value={counts.consent}
              tone={counts.consent > 0 ? "warn" : "good"}
            />
            {/* A coach cannot review flags; the federation does (the integrity board). */}
            <Stat label="Open flags" value={counts.flagged} hint="reviewed by the federation" />
          </>
        ) : (
          Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[5.5rem]" />)
        )}
      </div>

      {rows && (counts.overdue > 0 || counts.consent > 0 || counts.flagged > 0 || counts.readings > 0) ? (
        <Card className="border-amber-900/50 bg-amber-950/20">
          <SectionTitle>Needs you first</SectionTitle>
          <div className="flex flex-wrap gap-2">
            {counts.overdue > 0 ? (
              <Chip tone="warn" onClick={() => setFilter("overdue")} active={filter === "overdue"}>
                {counts.overdue} not measured in {STALE_DAYS} days
              </Chip>
            ) : null}
            {counts.consent > 0 ? (
              <Chip tone="warn" onClick={() => setFilter("consent")} active={filter === "consent"}>
                {counts.consent} minors without guardian consent
              </Chip>
            ) : null}
            {counts.flagged > 0 ? (
              <Chip tone="warn" onClick={() => setFilter("flagged")} active={filter === "flagged"}>
                {counts.flagged} flagged by the models
              </Chip>
            ) : null}
            {counts.readings > 0 ? (
              <Chip tone="warn" onClick={() => setFilter("readings")} active={filter === "readings"}>
                {counts.readings} {counts.readings === 1 ? "needs" : "need"} more height readings
              </Chip>
            ) : null}
            {filter !== "all" ? (
              <Chip onClick={() => setFilter("all")}>clear filter</Chip>
            ) : null}
          </div>
          {filter === "readings" ? (
            <p className="mt-3 max-w-2xl text-xs text-slate-400">
              The late-bloomer check needs a growth rate, and a growth rate needs several height
              readings. In the backtest it could not flag any late bloomer measured fewer times,
              and more than half of them were. Measure these players now and every few months.
            </p>
          ) : null}
        </Card>
      ) : null}

      <Card>
        <SectionTitle
          action={
            <span className="text-xs text-slate-500">
              sorted by longest since last measurement
            </span>
          }
        >
          {filter === "all" ? "All players" : `Filtered, ${visible.length} players`}
        </SectionTitle>

        {!rows ? (
          <div className="flex flex-col gap-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : visible.length === 0 ? (
          <Empty>Nothing here. That is a good state, not a bug.</Empty>
        ) : (
          <>
          {/* Phones: one card per player, so the flags are on screen without swiping a table
              sideways. The table below is for wider screens. */}
          <ul className="flex flex-col divide-y divide-slate-800 sm:hidden">
            {visible.map((r) => (
              <li key={r.player.id} className="flex flex-col gap-1.5 py-3">
                <div className="flex items-start justify-between gap-3">
                  <Link
                    href={`/players/${r.player.id}`}
                    className="font-semibold text-slate-100 hover:text-sky-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
                  >
                    {r.player.fullName}
                  </Link>
                  <Sparkline values={r.heightTrend} />
                </div>
                <p className="text-xs text-slate-400 tabular-nums">
                  {[r.player.position, r.ageLabel, r.heightCm ? `${r.heightCm} cm` : "no height yet"]
                    .filter(Boolean)
                    .join(" · ")}
                  {" · "}
                  <span className={cx(isStale(r.daysSinceLastLog) && "font-semibold text-amber-400")}>
                    measured {daysLabel(r.daysSinceLastLog)}
                  </span>
                </p>
                <RowChips row={r} />
              </li>
            ))}
          </ul>
          <div className="hidden sm:block">
          <Table>
            <thead>
              <tr>
                <Th />
                <Th>Player</Th>
                <Th>Pos</Th>
                <Th>Age</Th>
                <Th>Height</Th>
                <Th>Last logged</Th>
                <Th>Trend</Th>
                <Th>Flags</Th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr key={r.player.id} className="hover:bg-slate-900/40">
                  <Td className="w-9">
                    <Avatar size={28} name={r.player.fullName} />
                  </Td>
                  <Td>
                    <Link
                      href={`/players/${r.player.id}`}
                      className="font-semibold text-slate-100 hover:text-sky-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
                    >
                      {r.player.fullName}
                    </Link>
                  </Td>
                  <Td>{r.player.position}</Td>
                  <Td className="tabular-nums">{r.ageLabel}</Td>
                  <Td className="tabular-nums">{r.heightCm ? `${r.heightCm} cm` : "no data"}</Td>
                  <Td
                    className={cx(
                      "tabular-nums",
                      isStale(r.daysSinceLastLog) && "font-semibold text-amber-400",
                    )}
                  >
                    {daysLabel(r.daysSinceLastLog)}
                  </Td>
                  <Td>
                    <Sparkline values={r.heightTrend} />
                  </Td>
                  <Td>
                    <RowChips row={r} />
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
          </div>
          </>
        )}
      </Card>
    </div>
  );
}

/** The marks a squad row carries, the same in the phone list and the table. */
function RowChips({ row }: { row: SquadRow }) {
  if (row.heightReadingsNeeded === 0 && row.flags.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {row.heightReadingsNeeded > 0 ? (
        <Chip tone="warn">
          {row.heightReadingsNeeded} more height{" "}
          {row.heightReadingsNeeded === 1 ? "reading" : "readings"} needed
        </Chip>
      ) : null}
      {flagsByType(row.flags).map((f) => (
        <Chip key={f.type} tone={f.type === "consent" ? "warn" : "brand"}>
          {f.label}
          {times(f.count)}
        </Chip>
      ))}
    </div>
  );
}

const today = () => new Date().toISOString().slice(0, 10);
const MEASURE_SHOWN = 6;

/**
 * The players due a reading (not measured in STALE_DAYS, or short of the readings the
 * late-bloomer check needs), each with a height box. The list is fixed when the page loads, so a
 * row does not jump away the moment it is saved; it shows what was saved instead.
 */
function MeasuringDay({ rows, onSaved }: { rows: SquadRow[]; onSaved: () => void }) {
  const [due] = useState(() =>
    rows
      .filter((r) => isStale(r.daysSinceLastLog) || r.heightReadingsNeeded > 0)
      .sort((a, b) => (b.daysSinceLastLog ?? 9999) - (a.daysSinceLastLog ?? 9999)),
  );
  const [measuredAt, setMeasuredAt] = useState(today);
  const [saved, setSaved] = useState<Record<string, number>>({});
  const [all, setAll] = useState(false);
  const left = due.filter((r) => saved[r.player.id] == null).length;
  // A big squad would bury the rest of the page; the stalest come first anyway.
  const shown = all ? due : due.slice(0, MEASURE_SHOWN);

  if (due.length === 0) {
    return (
      <Card className={cx("border-l-4", coach.border)}>
        <h2 className="text-lg font-semibold">Measuring day</h2>
        <p className="mt-1 text-sm text-slate-400">Everyone has a recent reading. Nothing to measure today.</p>
      </Card>
    );
  }
  return (
    <Card className={cx("border-l-4", coach.border)}>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Measuring day</h2>
          <p className="text-sm text-slate-400">
            {left === 0
              ? "All done. Thank you."
              : `${left} of ${due.length} still to measure. Type a height and press Save.`}
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-400">
          Measured on
          <input
            type="date"
            value={measuredAt}
            max={today()}
            onChange={(e) => setMeasuredAt(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100"
          />
        </label>
      </div>
      <ul className="flex flex-col divide-y divide-slate-800">
        {shown.map((r) => (
          <MeasureRow
            key={r.player.id}
            row={r}
            measuredAt={measuredAt}
            saved={saved[r.player.id] ?? null}
            onSaved={(value) => {
              setSaved((now) => ({ ...now, [r.player.id]: value }));
              onSaved();
            }}
          />
        ))}
      </ul>
      {due.length > shown.length ? (
        <Button variant="ghost" size="sm" className="mt-2" onClick={() => setAll(true)}>
          Show all {due.length}
        </Button>
      ) : null}
    </Card>
  );
}

function MeasureRow({
  row,
  measuredAt,
  saved,
  onSaved,
}: {
  row: SquadRow;
  measuredAt: string;
  saved: number | null;
  onSaved: (value: number) => void;
}) {
  const [height, setHeight] = useState("");
  const [busy, setBusy] = useState(false);
  const [warnings, setWarnings] = useState<MeasurementWarning[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  async function save(acknowledgeWarnings: boolean) {
    const value = Number(height);
    setBusy(true);
    setProblem(null);
    try {
      await logMeasurement(row.player.id, {
        measuredAt,
        metrics: [{ metric: "height_cm", value, unit: "cm", confidence: "measured" }],
        acknowledgeWarnings,
      });
      setWarnings(null);
      onSaved(value);
    } catch (error) {
      const refusal = writeRefusal(error);
      if (refusal?.kind === "confirm") setWarnings(refusal.warnings);
      else if (refusal?.kind === "fix") setProblem(refusal.problems[0] ?? refusal.message);
      else setProblem("Not saved: the server could not be reached. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex flex-col gap-2 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <Avatar size={36} name={row.player.fullName} />
          <div className="min-w-0">
            <Link href={`/players/${row.player.id}`} className="block truncate font-semibold text-slate-100 hover:underline">
              {row.player.fullName}
            </Link>
            <p className="text-xs tabular-nums text-slate-500">
              {[row.ageLabel, row.heightCm ? `last ${row.heightCm} cm` : "no height yet"].join(" · ")}
              {" · "}
              <span className={cx(isStale(row.daysSinceLastLog) && "text-amber-400")}>
                measured {daysLabel(row.daysSinceLastLog)}
              </span>
            </p>
          </div>
        </div>
        {saved != null ? (
          <span className={cx("text-sm font-semibold tabular-nums", coach.text)}>Saved {saved} cm</span>
        ) : (
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (height) void save(false);
            }}
          >
            <input
              inputMode="decimal"
              placeholder="cm"
              value={height}
              onChange={(e) => {
                setHeight(e.target.value);
                setWarnings(null);
                setProblem(null);
              }}
              aria-label={`Height of ${row.player.fullName} in cm`}
              className="w-24 rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-right text-sm tabular-nums text-slate-100"
            />
            <Button type="submit" size="sm" variant="primary" disabled={busy || !height}>
              Save
            </Button>
          </form>
        )}
      </div>
      {warnings ? (
        <div className="rounded-md border border-amber-900/60 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
          {warnings.map((w) => (
            <p key={w.metric}>{w.message}</p>
          ))}
          <div className="mt-2 flex gap-2">
            <Button size="sm" disabled={busy} onClick={() => save(true)}>
              It is right, save it
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setWarnings(null)}>
              Let me fix it
            </Button>
          </div>
        </div>
      ) : null}
      {problem ? <p className="text-xs text-rose-300">{problem}</p> : null}
    </li>
  );
}

/**
 * The players growing fastest, from the API's growth rate (none for adults or without two
 * readings six months apart, so nobody is shown a number that is only measuring noise).
 */
function Growing({ rows }: { rows: SquadRow[] }) {
  const growing = rows
    .filter((r) => r.growthCmPerYear != null && r.growthCmPerYear > 0)
    .sort((a, b) => (b.growthCmPerYear ?? 0) - (a.growthCmPerYear ?? 0))
    .slice(0, 4);
  return (
    <Card>
      <h2 className="text-lg font-semibold">Growing fastest</h2>
      <p className="mb-3 text-xs text-slate-500">
        Height gained a year, from the latest reading and one at least six months earlier. A reading is good to about
        half a centimetre, so small differences between players mean little.
      </p>
      {growing.length === 0 ? (
        <p className="text-sm text-slate-400">
          Not enough readings yet: a growth rate needs two heights at least six months apart.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {growing.map((r) => (
            <li key={r.player.id} className="flex items-center justify-between gap-3">
              <Link href={`/players/${r.player.id}`} className="min-w-0 truncate text-slate-200 hover:underline">
                {r.player.fullName}
                <span className="ml-2 text-xs text-slate-500">{r.ageLabel}</span>
              </Link>
              <span className="flex shrink-0 items-center gap-2">
                <span className="hidden sm:inline">
                  <Sparkline values={r.heightTrend} />
                </span>
                <span className={cx("w-24 text-right text-sm font-semibold tabular-nums", coach.text)}>
                  +{r.growthCmPerYear} cm/yr
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** Late-bloomer flags on the coach's own players: good news, told as such. */
function Noticed({ rows }: { rows: SquadRow[] }) {
  const bloomers = rows.filter((r) => r.flags.some((f) => f.type === "late_bloomer"));
  return (
    <Card>
      <h2 className="text-lg font-semibold">What the models noticed</h2>
      <p className="mb-3 text-xs text-slate-500">
        A late bloomer is short for their age group but still growing well: behind in growth, not in ability. Worth
        patience. Federation staff review every flag.
      </p>
      {bloomers.length === 0 ? (
        <p className="text-sm text-slate-400">No late bloomers flagged in your squad.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {bloomers.map((r) => (
            <li key={r.player.id} className="flex items-center justify-between gap-3">
              <Link href={`/players/${r.player.id}`} className="min-w-0 truncate text-slate-200 hover:underline">
                {r.player.fullName}
                <span className="ml-2 text-xs text-slate-500">{r.ageLabel}</span>
              </Link>
              <Chip tone="good">late bloomer</Chip>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
