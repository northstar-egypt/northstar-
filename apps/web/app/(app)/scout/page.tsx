"use client";

/**
 * The scout's home (apps/api/app/services/scout_home.py). A scout opens NorthStar to find out
 * what is new, so it opens with their own shortlist and the players who stepped up, rather than
 * an empty search box.
 *
 * Everything on it comes from something already evaluated: the breakout detector (ml/README.md,
 * "Pro tier") and the late-bloomer flags. Each reason is the detector's own sentence. A saved
 * player the scout can no longer see is counted, never named.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { Avatar, Banner, Button, Card, Chip, Skeleton, inputClass } from "@/components/ui";
import { getScoutHome, removeFromShortlist, saveToShortlist } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cx } from "@/lib/format";
import { ROLE_IDENTITY } from "@/lib/roles";
import type { PlayerCard, ScoutHome } from "@/lib/types";

const scout = ROLE_IDENTITY.scout;

const QUICK = [
  { href: "/search", label: "Search players", hint: "Describe who you are looking for" },
  { href: "/gaps", label: "Team gaps", hint: "Where a club is weak, and who fits" },
  { href: "/explore/finishing", label: "Finishing", hint: "How shots become goals" },
  { href: "/compare", label: "Compare", hint: "Players side by side" },
];

function Who({ player }: { player: PlayerCard }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <Avatar size={40} name={player.fullName} />
      <div className="min-w-0">
        <Link href={`/players/${player.playerId}`} className="block truncate font-semibold text-slate-100 hover:underline">
          {player.fullName}
        </Link>
        <p className="truncate text-xs text-slate-500">
          {[player.position, player.ageLabel, player.club, player.tier ? `${player.tier} tier` : null]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>
    </div>
  );
}

export default function ScoutHomePage() {
  const { user } = useAuth();
  const [data, setData] = useState<ScoutHome | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let alive = true;
    getScoutHome()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [version]);

  const firstName = data?.firstName ?? user?.fullName?.split(" ")[0] ?? null;
  const saved = new Set(data?.shortlist.map((s) => s.playerId) ?? []);
  const refresh = () => setVersion((v) => v + 1);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className={cx("text-3xl font-bold tracking-tight", scout.text)}>{scout.greeting(firstName)}</h1>
        <p className="mt-1 text-slate-400">{scout.tagline}</p>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {QUICK.map((q) => (
          <Link
            key={q.href}
            href={q.href}
            className={cx(
              "rounded-lg border bg-slate-900/60 px-4 py-3 transition hover:bg-slate-900",
              scout.border,
            )}
          >
            <span className="block font-semibold text-slate-100">{q.label}</span>
            <span className="block text-xs text-slate-500">{q.hint}</span>
          </Link>
        ))}
      </div>

      {error ? <Banner tone="warn" title="Could not load your home">{error}</Banner> : null}
      {!data && !error ? <Skeleton className="h-72" /> : null}

      {data ? (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,4fr)]">
          <Card className={cx("self-start border-l-4", scout.border)}>
            <h2 className="mb-3 flex items-baseline justify-between gap-2">
              <span className="text-lg font-semibold">Your shortlist</span>
              <span className="text-sm text-slate-500">{data.shortlist.length} saved</span>
            </h2>
            {data.shortlist.length === 0 ? (
              <p className="text-sm text-slate-400">
                Nothing saved yet. Open any player and press <span className="font-semibold">Save to shortlist</span>,
                or save a breakout from the list here.
              </p>
            ) : (
              <ul className="flex flex-col divide-y divide-slate-800">
                {data.shortlist.map((item) => (
                  <ShortlistRow key={item.playerId} item={item} onChange={refresh} />
                ))}
              </ul>
            )}
            {data.withheld > 0 ? (
              <p className="mt-3 text-xs text-slate-500">
                {data.withheld} saved {data.withheld === 1 ? "player is" : "players are"} no longer visible to you,
                for example because consent was withdrawn, so not shown here.
              </p>
            ) : null}
          </Card>

          <div className="flex flex-col gap-5">
            <Card>
              <h2 className="mb-1 text-lg font-semibold">
                Stepped up{data.breakoutSeason ? ` in ${data.breakoutSeason}` : ""}
              </h2>
              <p className="mb-3 text-xs text-slate-500">
                Players aged 18 to 23 whose share of their team&apos;s chances clearly rose on the season before. A
                claim to check, not a verdict.
              </p>
              {data.breakouts.length === 0 ? (
                <p className="text-sm text-slate-400">No breakouts this season among the players you can see.</p>
              ) : (
                <ul className="flex flex-col gap-3">
                  {data.breakouts.map((b) => (
                    <li key={b.playerId} className={cx("rounded-md border-l-2 bg-slate-900/50 py-2 pl-3 pr-2", scout.border)}>
                      <div className="flex items-start justify-between gap-2">
                        <Who player={b} />
                        <SaveButton playerId={b.playerId} saved={saved.has(b.playerId)} onChange={refresh} />
                      </div>
                      <p className="mt-1 text-xs text-slate-400">{b.reason}.</p>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card>
              <h2 className="mb-1 text-lg font-semibold">Late bloomers</h2>
              <p className="mb-3 text-xs text-slate-500">
                Young players the models think are behind their age group in growth, not in ability. Federation staff
                review each one.
              </p>
              {data.lateBloomers.length === 0 ? (
                <p className="text-sm text-slate-400">None flagged among the players you can see.</p>
              ) : (
                <ul className="flex flex-col gap-3">
                  {data.lateBloomers.map((l) => (
                    <li key={l.playerId} className="flex flex-col gap-1">
                      <div className="flex items-start justify-between gap-2">
                        <Who player={l} />
                        <div className="flex shrink-0 items-center gap-1.5">
                          {l.status === "confirmed" ? <Chip tone="good">confirmed</Chip> : null}
                          <SaveButton playerId={l.playerId} saved={saved.has(l.playerId)} onChange={refresh} />
                        </div>
                      </div>
                      <p className="text-xs text-slate-400">{l.reason}</p>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function SaveButton({ playerId, saved, onChange }: { playerId: string; saved: boolean; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  if (saved) return <span className={cx("shrink-0 text-xs", scout.text)}>On your list</span>;
  return (
    <Button
      size="sm"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await saveToShortlist(playerId);
          onChange();
        } finally {
          setBusy(false);
        }
      }}
    >
      Save
    </Button>
  );
}

function ShortlistRow({ item, onChange }: { item: ScoutHome["shortlist"][number]; onChange: () => void }) {
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState(item.note);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
      onChange();
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
      <div className="flex items-start justify-between gap-2">
        <Who player={item} />
        <span className="shrink-0 text-xs text-slate-500">saved {item.savedAt}</span>
      </div>
      {editing ? (
        <div className="flex flex-col gap-2">
          <textarea
            className={cx(inputClass, "min-h-[4rem]")}
            value={note}
            maxLength={1000}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Why this player, and what to watch for"
            aria-label={`Note on ${item.fullName}`}
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="primary"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await saveToShortlist(item.playerId, note);
                  setEditing(false);
                })
              }
            >
              Save note
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setNote(item.note);
                setEditing(false);
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex items-start justify-between gap-2">
          <p className={cx("text-sm", item.note ? "text-slate-300" : "italic text-slate-500")}>
            {item.note || "No note yet."}
          </p>
          <div className="flex shrink-0 gap-1">
            <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
              {item.note ? "Edit note" : "Add note"}
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(() => removeFromShortlist(item.playerId))}>
              Remove
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}
