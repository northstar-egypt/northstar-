"use client";

/**
 * Squad Lab. Pick a formation, put players in it, see how well neighbours fit.
 *
 * Every number on this screen comes from POST /squad-lab/evaluate (apps/api/app/services/squad_lab.py),
 * which explains its own rules. This file only draws them. Where the API has no score, the
 * screen draws grey and says why; it never fills a gap.
 *
 * Managers (coaches) pick from their own club and save squads for it. Scouts and federation
 * staff pick from everyone they may see and try line-ups, with no save button: the API refuses
 * the save anyway.
 *
 * Moving players: drag a player from the list onto a slot, or drag one slot onto another to
 * swap them. On a phone, tap a slot and then tap a player in the list.
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Banner,
  Button,
  Card,
  Chip,
  SectionTitle,
  Skeleton,
  initials,
  inputClass,
} from "@/components/ui";
import {
  type LabSlots,
  deleteSquad,
  evaluateLineup,
  getLabCandidates,
  getSavedSquads,
  saveSquad,
} from "@/lib/api";
import { FlagIcon } from "@/components/flags";
import { useAuth } from "@/lib/auth";
import { cx } from "@/lib/format";
import type {
  LabBand,
  LabCandidate,
  LabEvaluation,
  LabLink,
  LabSlot,
  LabTrait,
  SavedSquad,
} from "@/lib/types";

const DEFAULT_FORMATION = "4-3-3";

const BAND_STROKE: Record<LabBand, string> = {
  green: "#34d399",
  yellow: "#fbbf24",
  red: "#fb7185",
  unknown: "#64748b",
};

const BAND_TEXT: Record<LabBand, string> = {
  green: "text-emerald-300",
  yellow: "text-amber-300",
  red: "text-rose-300",
  unknown: "text-slate-500",
};

const BAND_RING: Record<LabBand, string> = {
  green: "border-emerald-400",
  yellow: "border-amber-400",
  red: "border-rose-400",
  unknown: "border-slate-600",
};

const BAND_WORD: Record<LabBand, string> = {
  green: "good fit",
  yellow: "could work",
  red: "poor fit",
  unknown: "not enough data",
};

type Selection =
  | { kind: "slot"; id: string }
  | { kind: "link"; from: string; to: string }
  | null;

type Dragged =
  | { kind: "slot"; slotId: string }
  | { kind: "player"; playerId: string; card: LabCandidate };

function shortName(player: {
  fullName: string;
  knownAs: string | null;
}): string {
  if (player.knownAs) return player.knownAs;
  const words = player.fullName.split(/\s+/);
  return words.length > 2
    ? `${words[0]} ${words[words.length - 1]}`
    : player.fullName;
}

function scoreText(score: number | null): string {
  return score === null ? "–" : String(Math.round(score));
}

/** Carry players across a formation change: same slot id first, then any free slot in order. */
function carryOver(slots: LabSlots, from: LabSlot[], to: string[]): LabSlots {
  const next: LabSlots = {};
  const leftover: string[] = [];
  for (const slot of from) {
    const pid = slots[slot.slotId];
    if (!pid) continue;
    if (to.includes(slot.slotId)) next[slot.slotId] = pid;
    else leftover.push(pid);
  }
  for (const id of to) {
    if (!next[id] && leftover.length) next[id] = leftover.shift() ?? null;
  }
  return next;
}

export default function SquadLabPage() {
  const { user } = useAuth();
  const [formation, setFormation] = useState(DEFAULT_FORMATION);
  const [slots, setSlots] = useState<LabSlots>({});
  const [result, setResult] = useState<LabEvaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Selection>(null);
  const dragged = useRef<Dragged | null>(null);

  // Saved squads (managers only).
  const [maySave, setMaySave] = useState(false);
  const [saved, setSaved] = useState<SavedSquad[]>([]);
  const [squadId, setSquadId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    let alive = true;
    evaluateLineup(formation, slots)
      .then((r) => {
        if (!alive) return;
        setResult(r);
        setError(null);
      })
      .catch((err) => alive && setError(err.message));
    return () => {
      alive = false;
    };
  }, [formation, slots]);

  const loadSaved = useCallback(() => {
    getSavedSquads()
      .then((r) => {
        setMaySave(r.maySave);
        setSaved(r.squads);
      })
      .catch(() => setMaySave(false));
  }, []);
  useEffect(loadSaved, [loadSaved]);

  const placed = useMemo(
    () => Object.values(slots).filter((v): v is string => !!v),
    [slots],
  );
  const slotById = useMemo(
    () => new Map((result?.slots ?? []).map((s) => [s.slotId, s])),
    [result],
  );

  const place = (slotId: string, playerId: string) =>
    setSlots((current) => {
      const next: LabSlots = {};
      for (const [k, v] of Object.entries(current))
        if (v !== playerId) next[k] = v;
      next[slotId] = playerId;
      return next;
    });

  const swap = (a: string, b: string) =>
    setSlots((current) => ({
      ...current,
      [a]: current[b] ?? null,
      [b]: current[a] ?? null,
    }));

  const clearSlot = (slotId: string) =>
    setSlots((current) => ({ ...current, [slotId]: null }));

  const changeFormation = (next: string) => {
    if (!result || next === formation) return;
    // The new layout's slot ids come from the API; ask for an empty one, then carry players over.
    evaluateLineup(next, {})
      .then((empty) => {
        setSlots(
          carryOver(
            slots,
            result.slots,
            empty.slots.map((s) => s.slotId),
          ),
        );
        setFormation(next);
        setSelected(null);
      })
      .catch((err) => setError(err.message));
  };

  const drop = (slotId: string) => {
    const item = dragged.current;
    dragged.current = null;
    if (!item) return;
    if (item.kind === "slot") {
      if (item.slotId !== slotId) swap(item.slotId, slotId);
    } else {
      place(slotId, item.playerId);
    }
    setSelected({ kind: "slot", id: slotId });
  };

  const save = async (asNew: boolean) => {
    setSaveMessage(null);
    try {
      const out = await saveSquad(
        name.trim() || "Untitled squad",
        formation,
        slots,
        asNew ? undefined : (squadId ?? undefined),
      );
      setSquadId(out.id);
      setName(out.name);
      setSaveMessage(`Saved "${out.name}".`);
      loadSaved();
    } catch (err) {
      setSaveMessage((err as Error).message);
    }
  };

  const openSaved = (id: string) => {
    const squad = saved.find((s) => s.id === id);
    setConfirmDelete(false);
    setSaveMessage(null);
    if (!squad) {
      setSquadId(null);
      setName("");
      return;
    }
    setSquadId(squad.id);
    setName(squad.name);
    setFormation(squad.formation);
    setSlots(squad.slots);
    setSelected(null);
  };

  const remove = async () => {
    if (!squadId) return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    try {
      await deleteSquad(squadId);
      setSquadId(null);
      setName("");
      setConfirmDelete(false);
      setSaveMessage("Deleted.");
      loadSaved();
    } catch (err) {
      setSaveMessage((err as Error).message);
    }
  };

  const isManager = user?.role === "coach";
  const selectedSlot =
    selected?.kind === "slot" ? (slotById.get(selected.id) ?? null) : null;
  const selectedLink =
    selected?.kind === "link"
      ? (result?.links.find(
          (l) => l.from === selected.from && l.to === selected.to,
        ) ?? null)
      : null;

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-bold tracking-tight">Squad Lab</h1>
        <p className="text-sm text-slate-400">
          {isManager
            ? "Build a line-up from your squad, see how well neighbours fit, and save it for your club."
            : "Try players in a line-up to see if they fit. Saving squads is for club managers."}
        </p>
      </header>

      <Card className="flex flex-wrap items-center gap-3">
        <span className="text-xs font-medium text-slate-400">Formation</span>
        {(result?.formations ?? [DEFAULT_FORMATION]).map((f) => (
          <Chip
            key={f}
            active={f === formation}
            onClick={() => changeFormation(f)}
          >
            {f}
          </Chip>
        ))}
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto"
          onClick={() => {
            setSlots({});
            setSelected(null);
          }}
        >
          Clear pitch
        </Button>
      </Card>

      {maySave ? (
        <Card className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex min-w-[12rem] flex-1 flex-col gap-1">
              <span className="text-xs font-medium text-slate-400">
                Saved squads
              </span>
              <select
                className={inputClass}
                value={squadId ?? ""}
                onChange={(e) => openSaved(e.target.value)}
              >
                <option value="">New squad</option>
                {saved.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.formation})
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-w-[12rem] flex-1 flex-col gap-1">
              <span className="text-xs font-medium text-slate-400">Name</span>
              <input
                className={inputClass}
                value={name}
                maxLength={80}
                placeholder="e.g. Saturday against Ismaily"
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => save(false)}>
                {squadId ? "Save changes" : "Save squad"}
              </Button>
              {squadId ? (
                <>
                  <Button onClick={() => save(true)}>Save as new</Button>
                  <Button variant="danger" onClick={remove}>
                    {confirmDelete ? "Click again to delete" : "Delete"}
                  </Button>
                </>
              ) : null}
            </div>
          </div>
          {saveMessage ? (
            <p className="text-xs text-slate-400">{saveMessage}</p>
          ) : null}
        </Card>
      ) : null}

      {error ? <Banner tone="bad">{error}</Banner> : null}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="flex flex-col gap-3">
          {result ? <Headline result={result} /> : null}
          {result ? (
            <PitchBoard
              result={result}
              selected={selected}
              onSelect={setSelected}
              onDragSlot={(slotId) =>
                (dragged.current = { kind: "slot", slotId })
              }
              onDrop={drop}
            />
          ) : (
            <Skeleton className="aspect-[68/100] w-full" />
          )}
          <p className="text-xs text-slate-500">
            Click a position to open its player list, then click or drag a
            player onto it. Drag one card onto another to swap them. To remove a
            player, click his card and press Remove this player. Tap a line to
            see why it is that colour.
          </p>
        </div>

        <div className="flex flex-col gap-5">
          {selectedSlot ? (
            <SlotPanel
              slot={selectedSlot}
              exclude={placed}
              onPick={(c) => place(selectedSlot.slotId, c.playerId)}
              onDragPlayer={(c) =>
                (dragged.current = {
                  kind: "player",
                  playerId: c.playerId,
                  card: c,
                })
              }
              onClear={() => clearSlot(selectedSlot.slotId)}
              onClose={() => setSelected(null)}
            />
          ) : null}
          {selectedLink && result ? (
            <LinkPanel
              link={selectedLink}
              slots={slotById}
              onClose={() => setSelected(null)}
            />
          ) : null}
          {!selected ? (
            <Card className="flex flex-col gap-1 border-sky-900/70">
              <span className="text-sm font-semibold text-slate-100">
                Pick your players
              </span>
              <span className="text-sm text-slate-400">
                Click a position on the pitch. The players for that position
                open here, best fit first.
              </span>
            </Card>
          ) : null}
          {result ? (
            <TeamPanel result={result} />
          ) : (
            <Skeleton className="h-64 w-full" />
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ pitch */

function PitchBoard({
  result,
  selected,
  onSelect,
  onDragSlot,
  onDrop,
}: {
  result: LabEvaluation;
  selected: Selection;
  onSelect: (s: Selection) => void;
  onDragSlot: (slotId: string) => void;
  onDrop: (slotId: string) => void;
}) {
  const byId = new Map(result.slots.map((s) => [s.slotId, s]));
  const line = "rgba(148, 163, 184, 0.35)";
  return (
    <div className="relative aspect-[68/100] w-full overflow-hidden rounded-xl border border-slate-800 bg-[#0b1f17]">
      {/* Markings. Own goal at the bottom, attacking upwards. */}
      <svg
        viewBox="0 0 68 100"
        preserveAspectRatio="none"
        className="absolute inset-0 h-full w-full"
        aria-hidden
      >
        <g
          fill="none"
          stroke={line}
          strokeWidth="0.3"
          vectorEffect="non-scaling-stroke"
        >
          <rect x="1" y="1" width="66" height="98" />
          <line x1="1" y1="50" x2="67" y2="50" />
          <circle cx="34" cy="50" r="8.7" />
          <rect x="14" y="1" width="40" height="15.5" />
          <rect x="14" y="83.5" width="40" height="15.5" />
          <rect x="24.8" y="1" width="18.4" height="5.2" />
          <rect x="24.8" y="93.8" width="18.4" height="5.2" />
        </g>
      </svg>

      {/* Links between neighbours. */}
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className="absolute inset-0 h-full w-full"
      >
        {result.links.map((link) => {
          const a = byId.get(link.from);
          const b = byId.get(link.to);
          if (!a || !b) return null;
          const active =
            selected?.kind === "link" &&
            selected.from === link.from &&
            selected.to === link.to;
          const coords = { x1: a.x, y1: 100 - a.y, x2: b.x, y2: 100 - b.y };
          return (
            <g
              key={`${link.from}-${link.to}`}
              className="cursor-pointer"
              onClick={() =>
                onSelect({ kind: "link", from: link.from, to: link.to })
              }
            >
              <title>{`${link.label ?? "Link"}: ${link.score === null ? "not enough data" : Math.round(link.score)}`}</title>
              <line
                {...coords}
                stroke="transparent"
                strokeWidth="14"
                vectorEffect="non-scaling-stroke"
              />
              <line
                {...coords}
                stroke={BAND_STROKE[link.band]}
                strokeWidth={active ? 5 : 3}
                strokeDasharray={link.band === "unknown" ? "4 4" : undefined}
                strokeLinecap="round"
                opacity={link.band === "unknown" ? 0.5 : 0.9}
                vectorEffect="non-scaling-stroke"
              />
            </g>
          );
        })}
      </svg>

      {/* Players. */}
      {result.slots.map((slot) => {
        const active = selected?.kind === "slot" && selected.id === slot.slotId;
        return (
          <div
            key={slot.slotId}
            className="absolute -translate-x-1/2 translate-y-1/2"
            style={{ left: `${slot.x}%`, bottom: `${slot.y}%` }}
          >
            <button
              type="button"
              draggable={!!slot.player}
              onDragStart={(e) => {
                e.dataTransfer.setData("text/plain", slot.slotId);
                onDragSlot(slot.slotId);
              }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                onDrop(slot.slotId);
              }}
              onClick={() => onSelect({ kind: "slot", id: slot.slotId })}
              className="block focus:outline-none"
              aria-label={`${slot.roleName}: ${slot.player ? slot.player.fullName : "empty"}`}
            >
              {slot.player ? (
                <PlayerCard slot={slot} active={active} />
              ) : (
                <span className="flex flex-col items-center gap-0.5">
                  <span
                    className={cx(
                      "grid h-11 w-11 place-items-center rounded-full border-2 border-dashed border-slate-600 bg-slate-950/80 text-sm text-slate-500",
                      active &&
                        "ring-2 ring-sky-400 ring-offset-2 ring-offset-[#0b1f17]",
                    )}
                  >
                    +
                  </span>
                  <span className="rounded bg-slate-950/70 px-1 text-[0.65rem] text-slate-300">
                    {slot.state === "unavailable" ? "Unavailable" : slot.role}
                  </span>
                </span>
              )}
            </button>
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ side panels */

function TraitList({ traits }: { traits: LabTrait[] }) {
  if (!traits.length) return null;
  return (
    <ul className="flex flex-col gap-1.5">
      {traits.map((t) => (
        <li key={t.trait} className="flex flex-col gap-0.5">
          <div className="flex justify-between text-xs">
            <span className="text-slate-300">
              {t.label} <span className="text-slate-500">({t.measure})</span>
            </span>
            <span className="tabular-nums text-slate-400">{t.percentile}</span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-slate-800">
            <div
              className="h-1.5 rounded-full bg-sky-500"
              style={{ width: `${t.percentile}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

function SlotPanel({
  slot,
  exclude,
  onPick,
  onDragPlayer,
  onClear,
  onClose,
}: {
  slot: LabSlot;
  exclude: string[];
  onPick: (c: LabCandidate) => void;
  onDragPlayer: (c: LabCandidate) => void;
  onClear: () => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const [list, setList] = useState<LabCandidate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const excludeKey = exclude.join(",");

  useEffect(() => {
    let alive = true;
    const timer = setTimeout(() => {
      getLabCandidates(slot.role, q, excludeKey ? excludeKey.split(",") : [])
        .then((r) => alive && (setList(r), setError(null)))
        .catch((err) => alive && setError(err.message));
    }, 250);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [slot.role, q, excludeKey]);

  return (
    <Card className="flex flex-col gap-4">
      <SectionTitle
        action={
          <Button size="sm" variant="ghost" onClick={onClose}>
            Close
          </Button>
        }
      >
        {slot.roleName} ({slot.slotId})
      </SectionTitle>

      {slot.player ? (
        <div className="flex flex-col gap-2 rounded-lg border border-slate-800 p-3">
          <div className="flex items-start justify-between gap-2">
            <div className="flex flex-col">
              <Link
                href={`/players/${slot.player.playerId}`}
                className="text-sm font-semibold text-sky-300 hover:underline"
                dir="auto"
              >
                {slot.player.fullName}
              </Link>
              <span className="text-xs text-slate-500" dir="auto">
                {[
                  slot.player.position,
                  slot.player.tier === "youth" ? "academy" : slot.player.tier,
                  slot.player.ageLabel,
                  slot.player.club,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </div>
            <span
              className={cx(
                "text-lg font-semibold tabular-nums",
                BAND_TEXT[slot.band],
              )}
            >
              {scoreText(slot.score)}
            </span>
          </div>
          {slot.fit === "out_of_position" ? (
            <p className="text-xs text-amber-300">
              Out of position: he is ranked against {slot.roleName}s on what
              this slot needs.
            </p>
          ) : null}
          {slot.note ? (
            <p className="text-xs text-slate-400">{slot.note}</p>
          ) : null}
          {slot.source ? (
            <p className="text-xs text-slate-500">
              From his {slot.source}. Each bar is his rank out of 100 among{" "}
              {slot.rankedAmong ?? "players"} in this position.
            </p>
          ) : null}
          <TraitList traits={slot.traits} />
          <Button
            size="sm"
            variant="danger"
            onClick={onClear}
            className="self-start"
          >
            Remove this player
          </Button>
        </div>
      ) : slot.note ? (
        <p className="text-xs text-slate-400">{slot.note}</p>
      ) : null}

      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium text-slate-200">
          {slot.player
            ? "Swap him: click another player below"
            : "Click a player below to put him here"}
        </span>
        <input
          className={inputClass}
          value={q}
          placeholder="Search by name"
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search players by name"
        />
        {error ? <p className="text-xs text-rose-300">{error}</p> : null}
        {list === null ? (
          <Skeleton className="h-40 w-full" />
        ) : list.length === 0 ? (
          <p className="text-xs text-slate-500">No players found.</p>
        ) : (
          <ul className="flex max-h-[26rem] flex-col gap-1 overflow-y-auto pr-1">
            {list.map((c) => (
              <li key={c.playerId}>
                <button
                  type="button"
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData("text/plain", c.playerId);
                    onDragPlayer(c);
                  }}
                  onClick={() => onPick(c)}
                  className="flex w-full items-center gap-2 rounded-lg border border-transparent px-2 py-1.5 text-left hover:border-slate-700 hover:bg-slate-800/60"
                >
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span
                      className="truncate text-sm text-slate-200"
                      dir="auto"
                    >
                      {c.fullName}
                    </span>
                    <span
                      className="truncate text-xs text-slate-500"
                      dir="auto"
                    >
                      {[
                        c.position ?? "no position",
                        c.tier === "youth" ? "academy" : c.tier,
                        c.ageLabel,
                        c.club,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </span>
                  {!c.naturalPosition ? (
                    <Chip tone="warn">other position</Chip>
                  ) : null}
                  <span
                    className={cx(
                      "w-8 text-right text-sm tabular-nums",
                      BAND_TEXT[c.band],
                    )}
                  >
                    {scoreText(c.score)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs text-slate-500">
          Players who play this position come first, best score for this slot
          first. A dash means not enough data to score.
        </p>
      </div>
    </Card>
  );
}

function LinkPanel({
  link,
  slots,
  onClose,
}: {
  link: LabLink;
  slots: Map<string, LabSlot>;
  onClose: () => void;
}) {
  const sides = [link.from, link.to].map((id) => ({ id, slot: slots.get(id) }));
  return (
    <Card className="flex flex-col gap-3">
      <SectionTitle
        action={
          <Button size="sm" variant="ghost" onClick={onClose}>
            Close
          </Button>
        }
      >
        {link.label ?? "Link"}: {link.from} and {link.to}
      </SectionTitle>
      <div className="flex items-baseline gap-2">
        <span
          className={cx(
            "text-3xl font-semibold tabular-nums",
            BAND_TEXT[link.band],
          )}
        >
          {scoreText(link.score)}
        </span>
        <span className={cx("text-sm", BAND_TEXT[link.band])}>
          {BAND_WORD[link.band]}
        </span>
      </div>
      {link.why ? (
        <p className="text-sm text-slate-400">
          What this partnership needs: {link.why}.
        </p>
      ) : null}
      {link.note ? <p className="text-xs text-slate-400">{link.note}</p> : null}
      {sides.map(({ id, slot }) =>
        slot?.player && link.basis[id]?.length ? (
          <div key={id} className="flex flex-col gap-2">
            <span className="text-xs font-medium text-slate-300" dir="auto">
              {id}: {slot.player.fullName}
            </span>
            <TraitList traits={link.basis[id]} />
          </div>
        ) : null,
      )}
    </Card>
  );
}

function TeamPanel({ result }: { result: LabEvaluation }) {
  const { team } = result;
  const big = [
    {
      label: "Chemistry",
      score: team.chemistry,
      hint: `${team.chemistry.known} of ${team.chemistry.links} links scored`,
    },
    {
      label: "Balance",
      score: team.balance,
      hint: team.balance.weakest
        ? `weakest line: ${team.balance.weakest.toLowerCase()}`
        : (team.balance.note ?? ""),
    },
  ];
  return (
    <Card className="flex flex-col gap-4">
      <SectionTitle>Team score</SectionTitle>
      <div className="grid grid-cols-2 gap-3">
        {big.map((b) => (
          <div
            key={b.label}
            className="flex flex-col rounded-lg border border-slate-800 p-3"
          >
            <span className="text-xs text-slate-400">{b.label}</span>
            <span
              className={cx(
                "text-3xl font-semibold tabular-nums",
                BAND_TEXT[b.score.band],
              )}
            >
              {scoreText(b.score.score)}
            </span>
            <span className="text-xs text-slate-500">
              {b.score.score === null ? b.score.note : b.hint}
            </span>
          </div>
        ))}
      </div>
      <ul className="flex flex-col gap-2">
        {team.lines.map((line) => (
          <li key={line.key} className="flex flex-col gap-1">
            <div className="flex justify-between text-sm">
              <span className="text-slate-300">{line.label}</span>
              <span className={cx("tabular-nums", BAND_TEXT[line.band])}>
                {scoreText(line.score)}
              </span>
            </div>
            <div className="h-2 w-full rounded-full bg-slate-800">
              {line.score !== null ? (
                <div
                  className="h-2 rounded-full"
                  style={{
                    width: `${line.score}%`,
                    background: BAND_STROKE[line.band],
                  }}
                />
              ) : null}
            </div>
            <span className="text-xs text-slate-500">
              {line.score === null
                ? line.note
                : `${line.scored} of ${line.slots} players scored`}
            </span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-slate-500">
        {team.filled} of {team.slots} slots filled
        {team.outOfPosition ? `, ${team.outOfPosition} out of position` : ""}.
        Green is {">="} 60, yellow 40 to 60, red below 40, grey means not enough
        data.
      </p>
      <div className="flex flex-col gap-1.5 border-t border-slate-800 pt-3">
        <span className="text-xs font-medium text-slate-400">
          How to read this
        </span>
        <p className="text-xs text-slate-500">{result.about}</p>
        {result.caveats.map((c) => (
          <p key={c} className="text-xs text-slate-500">
            {c}
          </p>
        ))}
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------------ headline */

/** The two big numbers above the pitch: team rating and chemistry, each out of 100. */
function Headline({ result }: { result: LabEvaluation }) {
  const { rating, chemistry } = result.team;
  const items = [
    {
      label: "Team rating",
      score: rating,
      hint:
        rating.score === null
          ? rating.note
          : `average of ${rating.scored} outfield players`,
    },
    {
      label: "Chemistry",
      score: chemistry,
      hint:
        chemistry.score === null
          ? chemistry.note
          : `${chemistry.known} of ${chemistry.links} links`,
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-3">
      {items.map((item) => (
        <div
          key={item.label}
          className={cx(
            "flex items-center gap-3 rounded-xl border-2 bg-slate-950/80 px-4 py-3",
            BAND_RING[item.score.band],
          )}
        >
          <span
            className={cx(
              "text-4xl font-bold tabular-nums leading-none",
              BAND_TEXT[item.score.band],
            )}
          >
            {scoreText(item.score.score)}
            <span className="text-base font-medium text-slate-500">/100</span>
          </span>
          <span className="flex min-w-0 flex-col">
            <span className="text-sm font-semibold text-slate-100">
              {item.label}
            </span>
            <span className="text-xs text-slate-400">{item.hint}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ player card */

/** The card's frame, by how well the player fits the slot. */
const CARD_FRAME: Record<LabBand, string> = {
  green: "from-emerald-200 via-emerald-500 to-emerald-800",
  yellow: "from-amber-100 via-amber-400 to-amber-700",
  red: "from-rose-200 via-rose-500 to-rose-800",
  unknown: "from-slate-300 via-slate-500 to-slate-700",
};

const CARD_BODY: Record<LabBand, string> = {
  green: "from-emerald-800 via-emerald-950 to-slate-950",
  yellow: "from-amber-700 via-amber-950 to-slate-950",
  red: "from-rose-800 via-rose-950 to-slate-950",
  unknown: "from-slate-600 via-slate-800 to-slate-950",
};

// A shield with a cut-off bottom, the shape of the card.
const CARD_SHAPE = "polygon(0 0, 100% 0, 100% 86%, 50% 100%, 0 86%)";

/** A generic head-and-shoulders figure. The repo holds no real player photos. */
function Silhouette({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 36" className={className} aria-hidden>
      <circle cx="20" cy="11" r="8" fill="currentColor" />
      <path d="M3 36c0-9.5 7.6-15 17-15s17 5.5 17 15z" fill="currentColor" />
    </svg>
  );
}

/** A plain shield with the club's initials. Our own drawing, never a club's real badge. */
function ClubBadge({ name }: { name: string | null }) {
  const letters = name ? initials(name) : "–";
  return (
    <span
      className="relative grid h-[1.05rem] w-[0.95rem] place-items-center"
      title={name ?? "No club"}
    >
      <svg
        viewBox="0 0 20 22"
        className="absolute inset-0 h-full w-full"
        aria-hidden
      >
        <path
          d="M10 1l8 3v7c0 5-3.6 8.6-8 10-4.4-1.4-8-5-8-10V4z"
          fill="#0f172a"
          stroke="#cbd5e1"
          strokeWidth="1.4"
        />
      </svg>
      <span
        className="relative text-[0.38rem] font-bold leading-none text-slate-100"
        dir="auto"
      >
        {letters}
      </span>
    </span>
  );
}

/**
 * A player on the pitch: his score for this slot, position, nationality flag, club badge,
 * name and club. Our own card design.
 */
function PlayerCard({ slot, active }: { slot: LabSlot; active: boolean }) {
  const player = slot.player!;
  const nations = player.nationality?.length ? player.nationality : [];
  return (
    <span
      className={cx(
        "block drop-shadow-[0_6px_10px_rgba(0,0,0,0.6)] transition hover:-translate-y-0.5",
        active && "drop-shadow-[0_0_10px_rgba(56,189,248,0.9)]",
      )}
    >
      <span
        className={cx("block bg-gradient-to-br p-[2px]", CARD_FRAME[slot.band])}
        style={{ clipPath: CARD_SHAPE }}
      >
        <span
          className={cx(
            "relative flex h-[6.6rem] w-[4.6rem] flex-col items-center bg-gradient-to-b sm:h-[7.2rem] sm:w-[5.1rem]",
            CARD_BODY[slot.band],
          )}
          style={{ clipPath: CARD_SHAPE }}
        >
          {/* Shine across the top. */}
          <span className="pointer-events-none absolute inset-x-0 top-0 h-1/2 bg-gradient-to-b from-white/15 to-transparent" />

          <span className="absolute left-1.5 top-1 flex flex-col items-center leading-none">
            <span className="text-xl font-extrabold tabular-nums text-white sm:text-2xl">
              {scoreText(slot.score)}
            </span>
            <span className="mt-0.5 text-[0.6rem] font-bold tracking-wide text-white/85">
              {slot.role}
            </span>
            <span className="mt-0.5 flex flex-col items-center gap-0.5">
              {nations.slice(0, 2).map((code) => (
                <FlagIcon
                  key={code}
                  code={code}
                  className="h-[0.6rem] w-[0.9rem]"
                />
              ))}
              <ClubBadge name={player.club} />
            </span>
          </span>

          <Silhouette className="absolute right-0.5 top-2 h-12 w-12 text-white/25 sm:h-14 sm:w-14" />

          <span className="absolute inset-x-0 bottom-[0.75rem] flex flex-col items-center px-1">
            <span className="h-px w-4/5 bg-white/25" />
            <span
              className="mt-0.5 w-full truncate text-center text-[0.66rem] font-bold leading-tight text-white"
              dir="auto"
            >
              {shortName(player)}
            </span>
            <span
              className="w-full truncate text-center text-[0.52rem] leading-tight text-white/60"
              dir="auto"
            >
              {player.club ?? "no club"}
            </span>
          </span>
        </span>
      </span>
      {slot.fit === "out_of_position" ? (
        <span className="mx-auto -mt-1 block w-fit rounded bg-amber-400 px-1 text-[0.5rem] font-bold text-slate-950">
          out of position
        </span>
      ) : null}
    </span>
  );
}
