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
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { GrowthChart, PercentileBar, Pitch, Radar, ShareRange, TennisTable } from "@/components/charts";
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
  inputClass,
} from "@/components/ui";
import {
  getPlayerEvents,
  getProfile,
  getRadar,
  getSimilar,
  getSummary,
  withdrawConsent,
  writeRefusal,
} from "@/lib/api";
import { canAccess, useAuth } from "@/lib/auth";
import { num, ordinal, shortDate } from "@/lib/format";
import type {
  Opponent,
  PerformanceSection,
  PlayerEvents,
  PlayerProfile,
  PlayerRadar,
  ProfileSummary,
  Rating,
  SimilarPlayers,
  SummaryStat,
} from "@/lib/types";

/** "8 readings over 2.4 years", from the player's own measurements. */
function measuredSpan(measured: { date: string }[]): string {
  if (measured.length === 0) return "no readings";
  if (measured.length === 1) return "1 reading";
  const days =
    (new Date(measured[measured.length - 1].date).getTime() - new Date(measured[0].date).getTime()) /
    86_400_000;
  const years = days / 365.25;
  const span = years >= 1 ? `${years.toFixed(1)} years` : `${Math.round(days / 30.44)} months`;
  return `${measured.length} readings over ${span}`;
}

export default function PlayerProfilePage() {
  // The route segment is read with useParams rather than taken as a `params` prop. From Next 15
  // that prop is a Promise, and unwrapping it in a client component needs React 19. This hook is
  // synchronous, is the documented way to read the segment from a client component, and keeps us
  // on React 18.
  const playerId = String(useParams().id ?? "");
  const { user } = useAuth();
  const [data, setData] = useState<PlayerProfile | null | "missing">(null);
  // Bumped after a write, so the whole profile is fetched again and every part of it that
  // depends on consent (percentiles, forecast, flags) shows the new state.
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let alive = true;
    getProfile(playerId).then((p) => alive && setData(p ?? "missing"));
    return () => {
      alive = false;
    };
  }, [playerId, version]);

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
                {[
                  data.organizationName,
                  p.position?.replace(/_/g, " "),
                  p.tier ? `${p.tier} tier` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
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

      {/* written summary, loaded after the profile because a local model takes seconds */}
      <SummaryCard playerId={playerId} />

      {/* growth and maturity */}
      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <Card>
          <SectionTitle
            action={<span className="text-xs text-slate-500">{measuredSpan(data.growth.measured)}</span>}
          >
            Height over time
          </SectionTitle>
          <GrowthChart series={data.growth} />
          {/* Which model, how its band was checked on this database, or why there is none. */}
          {data.growth.forecastNote ? (
            <p className="mt-2 text-xs text-slate-500">{data.growth.forecastNote}</p>
          ) : null}
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
                    ? "Behind their age group, which is the late bloomer signal. Short for their age is not the same as short."
                    : "In line with their age group."}
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
        <SectionTitle>Against their age group</SectionTitle>
        {data.percentilesNote ? (
          <p className="text-sm text-slate-500">{data.percentilesNote}</p>
        ) : null}
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

      {/* strength against other players, for sports that have a rating */}
      {data.rating ? <RatingCard rating={data.rating} /> : null}

      <RadarCard playerId={playerId} />

      {data.player.primarySport === "football" ? <ShotMapCard playerId={playerId} /> : null}
      {data.player.primarySport === "table_tennis" ? <PointsCard playerId={playerId} /> : null}

      {/* performance, laid out by the sport module */}
      {data.performance.length === 0 ? (
        <Card>
          <SectionTitle>Performance</SectionTitle>
          <p className="text-sm text-slate-500">No performance entries recorded.</p>
        </Card>
      ) : (
        data.performance.map((section) => (
          <PerformanceCard key={section.schemaRef} section={section} />
        ))
      )}

      <SimilarCard playerId={playerId} />

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
        {data.permissions.canEdit ? (
          <WithdrawConsent
            playerId={p.id}
            isMinor={p.isMinor}
            consents={data.provenance.consents}
            onDone={() => setVersion((v) => v + 1)}
          />
        ) : null}
      </Card>
    </div>
  );
}

const WITHDRAWABLE: { purpose: string; label: string; effect: string }[] = [
  {
    purpose: "analytics",
    label: "Analytics",
    effect: "no rating, forecast, percentiles, talent flags or search matches",
  },
  {
    purpose: "scouting_visibility",
    label: "Scouting visibility",
    effect: "a minor is hidden from scouts again",
  },
];

/**
 * Recording a withdrawal of part of the sign-up consent. The guardian (or the adult player)
 * withdraws; whoever holds the record writes it down here. Data storage is not offered:
 * withdrawing it means deleting the record, which is a separate erasure request.
 */
function WithdrawConsent({
  playerId,
  isMinor,
  consents,
  onDone,
}: {
  playerId: string;
  isMinor: boolean;
  consents: { purpose: string; granted: boolean }[];
  onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState<string[]>([]);
  const [guardian, setGuardian] = useState("");
  const [saving, setSaving] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);

  const granted = new Set(consents.filter((c) => c.granted).map((c) => c.purpose));
  const offered = WITHDRAWABLE.filter((w) => granted.has(w.purpose));
  if (offered.length === 0) return null;

  if (!open) {
    return (
      <div className="mt-3">
        <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
          Record a consent withdrawal
        </Button>
      </div>
    );
  }

  const ready = chosen.length > 0 && (!isMinor || guardian.trim().length > 0) && !saving;

  async function save() {
    setSaving(true);
    setProblems([]);
    try {
      await withdrawConsent(playerId, {
        purposes: chosen,
        ...(isMinor ? { guardianName: guardian } : {}),
      });
      setOpen(false);
      setChosen([]);
      onDone();
    } catch (error) {
      const refusal = writeRefusal(error);
      setProblems(
        refusal?.kind === "fix" && refusal.problems.length
          ? refusal.problems
          : ["Nothing was saved. Try again."],
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-3 flex flex-col gap-2 rounded-md border border-slate-800 bg-slate-950/40 px-3 py-3">
      <Label>Record a consent withdrawal</Label>
      {offered.map((w) => (
        <label key={w.purpose} className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={chosen.includes(w.purpose)}
            onChange={(e) =>
              setChosen((xs) =>
                e.target.checked ? [...xs, w.purpose] : xs.filter((x) => x !== w.purpose),
              )
            }
            className="mt-0.5 h-4 w-4 accent-sky-500"
          />
          <span>
            {w.label}
            <span className="ml-1 text-xs text-slate-500">({w.effect})</span>
          </span>
        </label>
      ))}
      {isMinor ? (
        <div className="flex flex-col gap-1">
          <span className="text-xs text-slate-400">Guardian withdrawing consent</span>
          <input
            aria-label="Guardian withdrawing consent"
            value={guardian}
            onChange={(e) => setGuardian(e.target.value)}
            className={inputClass}
            autoComplete="off"
          />
        </div>
      ) : null}
      {problems.length ? (
        <ul className="text-xs text-rose-300">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : null}
      <span className="text-xs text-slate-500">
        Takes effect at once. The earlier consent stays on record with the date it ended.
      </span>
      <div className="flex gap-2">
        <Button size="sm" variant="danger" disabled={!ready} onClick={save}>
          {saving ? "Saving" : "Withdraw"}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

/**
 * The written summary. The API builds it from this same page's numbers, has a local model
 * phrase it, and withholds it if the reply holds any number or flag the page does not show.
 * When there is no summary the note says why (the model is off, or the reply was withheld),
 * in small print, because the rest of the page is complete without it.
 */
function SummaryCard({ playerId }: { playerId: string }) {
  const [summary, setSummary] = useState<ProfileSummary | "loading" | "failed">("loading");

  useEffect(() => {
    let alive = true;
    setSummary("loading");
    getSummary(playerId)
      .then((s) => alive && setSummary(s ?? "failed"))
      .catch(() => alive && setSummary("failed"));
    return () => {
      alive = false;
    };
  }, [playerId]);

  if (summary === "failed") return null;

  if (summary === "loading") {
    return (
      <Card className="bg-slate-900/70">
        <SectionTitle>Summary</SectionTitle>
        <Skeleton className="h-12" />
        <p className="mt-2 text-xs text-slate-500">A local model is writing this. The first time, it can take a minute or two, sometimes more.</p>
      </Card>
    );
  }

  if (!summary.summary) {
    return <p className="text-xs text-slate-500">No written summary. {summary.note}</p>;
  }

  return (
    <Card className="bg-slate-900/70">
      <SectionTitle>Summary</SectionTitle>
      <p className="text-sm leading-relaxed text-slate-300">{summary.summary}</p>
      <p className="mt-2 text-xs text-slate-500">{summary.note}</p>
    </Card>
  );
}

/**
 * Percentiles of the player's match statistics among comparable players
 * (apps/api/app/services/radar.py), as a radar and as a list with the actual values. Its own
 * request, so the profile never waits for it.
 */
function RadarCard({ playerId }: { playerId: string }) {
  const { user } = useAuth();
  const [radar, setRadar] = useState<PlayerRadar | "loading" | "failed">("loading");

  useEffect(() => {
    let alive = true;
    setRadar("loading");
    getRadar(playerId)
      .then((r) => alive && setRadar(r ?? "failed"))
      .catch(() => alive && setRadar("failed"));
    return () => {
      alive = false;
    };
  }, [playerId]);

  if (radar === "failed") return null;
  return (
    <Card>
      <SectionTitle>Match statistics against comparable players</SectionTitle>
      {radar === "loading" ? (
        <Skeleton className="h-64" />
      ) : radar.axes.length === 0 ? (
        <p className="text-sm text-slate-500">{radar.note}</p>
      ) : (
        <div className="grid items-center gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <Radar
            axes={radar.axes.map((a) => ({ key: a.key, label: a.label }))}
            series={[
              {
                name: "This player",
                values: Object.fromEntries(radar.axes.map((a) => [a.key, a.percentile])),
              },
            ]}
          />
          <div>
            {radar.population ? (
              <p className="mb-2 text-xs text-slate-400">Among {radar.population}.</p>
            ) : null}
            <ul className="flex flex-col gap-1 text-sm">
              {radar.axes.map((a) => (
                <li key={a.key} className="flex items-baseline justify-between gap-3">
                  <span className="text-slate-300">{a.label}</span>
                  <span className="tabular-nums text-slate-400">
                    {a.value} {a.unit}
                    <span className="ml-2 inline-block w-14 text-right font-semibold text-slate-100">
                      {a.percentile == null ? "n/a" : ordinal(a.percentile)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-slate-500">{radar.note}</p>
            {canAccess(user?.role, "/explore") ? (
              <Link
                href={`/explore?focus=${encodeURIComponent(playerId)}`}
                className="mt-2 inline-block text-sm text-sky-300 hover:underline"
              >
                See them among all comparable players
              </Link>
            ) : null}
          </div>
        </div>
      )}
    </Card>
  );
}

const SHOT_OUTCOMES: { key: string; label: string; colour: string }[] = [
  { key: "goal", label: "Goal", colour: "#34d399" },
  { key: "on_target", label: "Saved", colour: "#38bdf8" },
  { key: "off_target", label: "Off target", colour: "#94a3b8" },
  { key: "blocked", label: "Blocked", colour: "#f59e0b" },
];

/**
 * Where the player's shots came from, as coaches tagged them from match video
 * (apps/api/app/services/events.py). Shown only when there are tagged shots: an empty map says
 * nothing about the player, only that nobody has tagged their matches.
 */
function ShotMapCard({ playerId }: { playerId: string }) {
  const [shots, setShots] = useState<PlayerEvents | null>(null);

  useEffect(() => {
    let alive = true;
    getPlayerEvents(playerId, "shot")
      .then((s) => alive && setShots(s))
      .catch(() => alive && setShots(null));
    return () => {
      alive = false;
    };
  }, [playerId]);

  if (!shots || shots.events.length === 0) return null;
  const colour = Object.fromEntries(SHOT_OUTCOMES.map((o) => [o.key, o.colour]));
  const placed = shots.events.filter((e) => e.x != null && e.y != null);
  return (
    <Card>
      <SectionTitle>Shot map</SectionTitle>
      <div className="grid items-center gap-6 sm:grid-cols-[minmax(0,16rem)_minmax(0,14rem)]">
        {/* Half a pitch is taller than it is wide, so it is kept small. */}
        <Pitch
          half
          markers={placed.map((e) => ({
            id: e.id,
            x: e.x as number,
            y: e.y as number,
            colour: colour[e.outcome] ?? "#94a3b8",
            label: `${shortDate(e.matchDate)}${e.matchLabel ? `, ${e.matchLabel}` : ""}: ${e.outcome.replace("_", " ")}`,
          }))}
        />
        <ul className="flex flex-col gap-1 text-sm">
          {SHOT_OUTCOMES.map((o) => (
            <li key={o.key} className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-slate-300">
                <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: o.colour }} />
                {o.label}
              </span>
              <span className="tabular-nums text-slate-100">{shots.counts[`shot.${o.key}`] ?? 0}</span>
            </li>
          ))}
          <li className="mt-1 flex justify-between border-t border-slate-800 pt-1 text-slate-400">
            <span>Shots</span>
            <span className="tabular-nums">{shots.events.length}</span>
          </li>
        </ul>
      </div>
      <p className="mt-2 text-xs text-slate-500">
        {shots.note}
        {placed.length < shots.events.length
          ? ` ${shots.events.length - placed.length} were tagged without a place on the pitch.`
          : ""}
      </p>
    </Card>
  );
}

const POINT_OUTCOMES: { type: string; key: string; label: string; colour: string }[] = [
  { type: "point_won", key: "winner", label: "Winners", colour: "#34d399" },
  { type: "point_won", key: "service_winner", label: "Service winners", colour: "#6ee7b7" },
  { type: "point_won", key: "opponent_error", label: "Opponent's errors", colour: "#a7f3d0" },
  { type: "point_lost", key: "unforced_error", label: "Unforced errors", colour: "#f87171" },
  { type: "point_lost", key: "forced_error", label: "Forced errors", colour: "#fca5a5" },
  { type: "point_lost", key: "opponent_winner", label: "Opponent's winners", colour: "#fecaca" },
];

/**
 * How a table tennis player wins and loses points, from points coaches tagged on match video
 * (apps/api/app/services/events.py). Shares, not counts, so a player with more tagged matches
 * does not look different for that alone. The table shows where their winners landed and where
 * their unforced errors went. Shown only when points have been tagged.
 */
function PointsCard({ playerId }: { playerId: string }) {
  const [points, setPoints] = useState<PlayerEvents | null>(null);

  useEffect(() => {
    let alive = true;
    getPlayerEvents(playerId)
      .then((p) => alive && setPoints(p))
      .catch(() => alive && setPoints(null));
    return () => {
      alive = false;
    };
  }, [playerId]);

  if (!points || points.events.length === 0) return null;
  const total = (type: string) =>
    POINT_OUTCOMES.filter((o) => o.type === type).reduce((n, o) => n + (points.counts[`${o.type}.${o.key}`] ?? 0), 0);
  const won = total("point_won");
  const lost = total("point_lost");
  const shown = points.events.filter(
    (e) => e.x != null && e.y != null && (e.outcome === "winner" || e.outcome === "unforced_error"),
  );

  return (
    <Card>
      <SectionTitle>How points are won and lost</SectionTitle>
      <div className="grid gap-6 md:grid-cols-2">
        <div className="flex flex-col gap-3">
          {(["point_won", "point_lost"] as const).map((type) => {
            const of = type === "point_won" ? won : lost;
            return (
              <div key={type}>
                <p className="mb-1 text-xs text-slate-400">
                  {type === "point_won" ? `Points won: ${won}` : `Points lost: ${lost}`}
                </p>
                <ul className="flex flex-col gap-1 text-sm">
                  {POINT_OUTCOMES.filter((o) => o.type === type).map((o) => {
                    const n = points.counts[`${o.type}.${o.key}`] ?? 0;
                    const share = of ? n / of : 0;
                    return (
                      <li key={o.key} className="grid grid-cols-[9rem_1fr_3rem] items-center gap-2">
                        <span className="text-slate-300">{o.label}</span>
                        <span className="h-2 rounded bg-slate-800">
                          <span className="block h-2 rounded" style={{ width: `${share * 100}%`, background: o.colour }} />
                        </span>
                        <span className="text-right tabular-nums text-slate-100">{Math.round(share * 100)}%</span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>
        <div>
          <TennisTable
            markers={shown.map((e) => ({
              id: e.id,
              x: e.x as number,
              y: e.y as number,
              colour: e.outcome === "winner" ? "#34d399" : "#f87171",
              label: `${shortDate(e.matchDate)}: ${e.outcome === "winner" ? "winner" : "unforced error"}`,
            }))}
          />
          <p className="mt-1 text-xs text-slate-500">
            Where their winners landed (green) and their unforced errors went (red).
          </p>
        </div>
      </div>
      <p className="mt-2 text-xs text-slate-500">{points.note}</p>
    </Card>
  );
}

/**
 * Players whose match record looks most like this one's (ml/similarity.py, graded in
 * ml/README.md, "Player similarity"). Its own request, so the profile never waits for it. The
 * API lists only players the caller may see, and compares nobody without analytics consent.
 */
function SimilarCard({ playerId }: { playerId: string }) {
  const [similar, setSimilar] = useState<SimilarPlayers | "loading" | "failed">("loading");

  useEffect(() => {
    let alive = true;
    setSimilar("loading");
    getSimilar(playerId)
      .then((s) => alive && setSimilar(s ?? "failed"))
      .catch(() => alive && setSimilar("failed"));
    return () => {
      alive = false;
    };
  }, [playerId]);

  if (similar === "failed") return null;

  return (
    <Card>
      <SectionTitle>Similar players</SectionTitle>
      {similar === "loading" ? (
        <Skeleton className="h-16" />
      ) : similar.items.length === 0 ? (
        <p className="text-sm text-slate-500">{similar.note}</p>
      ) : (
        <>
          <ul className="flex flex-col divide-y divide-slate-800">
            {similar.items.map((p) => (
              <li key={p.playerId} className="flex flex-wrap items-baseline justify-between gap-2 py-2">
                <Link href={`/players/${p.playerId}`} className="font-semibold text-slate-100 hover:text-sky-300">
                  {p.fullName}
                </Link>
                <span className="text-xs text-slate-400">
                  {[p.position, p.ageLabel].filter(Boolean).join(" · ")} · alike on {p.alike.join(", ")}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-slate-500">{similar.note}</p>
        </>
      )}
    </Card>
  );
}

const pct = (x: number) => `${Math.round(x * 100)}%`;

/**
 * Strength against other players, from who they played and how many points they won. Always
 * drawn with its range; when the range is too wide the API sends no number and the card says
 * why instead. The model and how it was checked are in ml/README.md, "Table tennis rating".
 */
function RatingCard({ rating }: { rating: Rating }) {
  return (
    <Card>
      <SectionTitle
        action={
          <span className="text-xs text-slate-500">
            {rating.ratedMatches} rated match{rating.ratedMatches === 1 ? "" : "es"}
          </span>
        }
      >
        Strength against other players
      </SectionTitle>
      {rating.shown && rating.pointShare != null && rating.low != null && rating.high != null ? (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-2xl font-bold tabular-nums">{pct(rating.pointShare)}</span>
            <span className="text-sm text-slate-400">
              of points won against an average opponent, likely between {pct(rating.low)} and{" "}
              {pct(rating.high)}
            </span>
          </div>
          <ShareRange value={rating.pointShare} low={rating.low} high={rating.high} />
          {rating.matchWin != null ? (
            <p className="text-sm text-slate-300">
              Against that opponent they would win about {pct(rating.matchWin)} of best-of-five
              matches. A few points in a hundred either way make a large difference over a match.
            </p>
          ) : null}
          <p className="text-xs text-slate-500">
            An average opponent means an average among {rating.population}. Every point counts,
            adjusted for who it was against. Only confirmed matches count: a self-submitted
            result counts once the opponent logs it too or it comes from a results feed or a
            coach.
          </p>
        </div>
      ) : (
        <p className="text-sm text-slate-500">{rating.note}</p>
      )}
    </Card>
  );
}

/** Who a match was against, as far as this viewer may know, and how strong they were then. */
function OpponentCell({ opponent }: { opponent: Opponent | null | undefined }) {
  if (!opponent) return <span className="text-slate-600">-</span>;
  const who = !opponent.registered ? (
    <span className="text-slate-500">not on the platform</span>
  ) : opponent.id && opponent.name ? (
    <Link href={`/players/${opponent.id}`} className="text-sky-300 hover:underline">
      {opponent.name}
    </Link>
  ) : (
    <span className="text-slate-400">a registered player</span>
  );
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {who}
      {opponent.strength ? (
        <span
          className="tabular-nums text-xs text-slate-500"
          title={`Going into that month: ${pct(opponent.strength.low)} to ${pct(opponent.strength.high)} of points against an average opponent`}
        >
          rated {pct(opponent.strength.pointShare)}
        </span>
      ) : null}
      {!opponent.counted ? (
        <span
          className="text-[0.7rem] text-amber-400"
          title="Does not count toward ratings: either nobody but the player has confirmed it, or it cannot be used for analytics"
        >
          not counted
        </span>
      ) : null}
    </span>
  );
}

/**
 * One kind of performance record. Every label, unit and statistic here comes from the sport
 * module (packages/shared/sports/<sport>.json) by way of the API. Nothing in this component
 * names a sport, a metric or a rule: a football season and a table tennis match go through
 * the same code, and a new sport's module renders here without a change to this file.
 */
// Rows shown before "Show all": enough for the recent picture, short enough for a phone.
const RECENT_ROWS = 8;

function PerformanceCard({ section }: { section: PerformanceSection }) {
  const hasOpponents = section.entries.some((e) => e.opponent);
  // Only when some record names one: most coach-logged matches have no event.
  const hasEvents = section.entries.some((e) => e.event);
  const [showAll, setShowAll] = useState(false);
  // A row that fails validation is never hidden behind the button: it is what a reviewer needs.
  const shown = showAll
    ? section.entries
    : section.entries.filter((e, i) => i < RECENT_ROWS || e.problems);
  const hidden = section.entries.length - shown.length;
  return (
    <Card>
      <SectionTitle action={<Chip tone="brand">{section.schemaRef}</Chip>}>
        {`Performance: ${section.label.toLowerCase()}`}
      </SectionTitle>

      {section.summary.length > 0 ? (
        <div className="mb-3 flex flex-wrap gap-2">
          {section.summary.map((stat) => (
            <div
              key={stat.key}
              className="min-w-[7rem] rounded-md border border-slate-800 bg-slate-900/40 px-3 py-2"
            >
              <Label>{stat.label}</Label>
              <span className="block text-xl font-bold tabular-nums">{formatStat(stat)}</span>
              <span className="text-[0.7rem] text-slate-500">over {stat.basis} records</span>
            </div>
          ))}
        </div>
      ) : null}

      {!section.known ? (
        <Banner tone="info" title="No sport module for these records">
          Shown with their raw field names. Nothing validates them until a module in
          packages/shared/sports defines {section.schemaRef}.
        </Banner>
      ) : null}

      <Table>
        <thead>
          <tr>
            <Th>Period</Th>
            {hasOpponents ? <Th>Opponent</Th> : null}
            {hasEvents ? <Th>Event</Th> : null}
            {section.columns.map((c) => (
              <Th key={c.key}>
                {c.label}
                {c.unit ? ` (${c.unit})` : ""}
              </Th>
            ))}
            <Th>Source</Th>
          </tr>
        </thead>
        <tbody>
          {shown.map((e) => (
            <tr key={e.id} className={e.problems ? "bg-amber-500/10" : undefined}>
              <Td className="whitespace-nowrap">
                {shortDate(e.periodStart)}
                {e.periodEnd ? ` to ${shortDate(e.periodEnd)}` : ""}
                {e.problems ? (
                  <span className="block text-[0.7rem] text-amber-400" title={e.problems.join("; ")}>
                    fails validation: {e.problems[0]}
                  </span>
                ) : null}
              </Td>
              {hasOpponents ? (
                <Td>
                  <OpponentCell opponent={e.opponent} />
                </Td>
              ) : null}
              {hasEvents ? <Td className="text-slate-300">{e.event ?? "-"}</Td> : null}
              {section.columns.map((c) => (
                <Td key={c.key} className="tabular-nums">
                  {String(e.metrics[c.key] ?? "-")}
                </Td>
              ))}
              <Td className="whitespace-nowrap text-slate-500">{e.source.replace(/_/g, " ")}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {hidden > 0 ? (
        <Button variant="ghost" className="mt-2" onClick={() => setShowAll(true)}>
          Show all {section.entries.length} records
        </Button>
      ) : null}

      {section.excludedFromSummary > 0 ? (
        <p className="mt-2 text-xs text-slate-500">
          {section.excludedFromSummary} record{section.excludedFromSummary === 1 ? "" : "s"} fail
          {section.excludedFromSummary === 1 ? "s" : ""} the sport&apos;s validation rules and
          {section.excludedFromSummary === 1 ? " is" : " are"} left out of the figures above.
        </p>
      ) : null}
    </Card>
  );
}

function formatStat(stat: SummaryStat): string {
  return stat.format === "percent" ? `${Math.round(stat.value * 100)}%` : stat.value.toFixed(2);
}
