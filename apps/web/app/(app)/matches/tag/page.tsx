"use client";

/**
 * Tag a match from video. Coaches only.
 *
 * The coach opens a recording from their own computer or phone; it plays here and is never
 * uploaded. They pick a player, click where it happened (the video pauses): on the pitch in
 * football, on the table in table tennis, where the deciding ball landed. Then the type and the
 * outcome, by button or by key. Each tag is saved at once with the time in the video, so it can
 * be found and checked again from the list.
 *
 * The event types and outcomes come from the sport module (GET /sports, `events`), so this
 * screen knows no sport's rules; it only knows which surface to draw. Beside the list, each player's tags are added up into
 * match totals and set next to what was logged for that date: two records of one match that
 * disagree are worth a look.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pitch, TennisTable, type PitchMarker } from "@/components/charts";
import { Banner, Button, Card, Field, SectionTitle, inputClass } from "@/components/ui";
import { getMatchTags, getSports, getSquad, tagEvent, untagEvent } from "@/lib/api";
import { cx } from "@/lib/format";
import type { EventType, MatchTags, SportModule, SquadRow } from "@/lib/types";

const TYPE_COLOURS = ["#f59e0b", "#38bdf8", "#34d399", "#f472b6", "#a78bfa"];
// Where a type's meaning has an obvious colour, it gets it.
const FIXED_COLOURS: Record<string, string> = { point_won: "#34d399", point_lost: "#f87171" };

function clock(seconds: number | null): string {
  if (seconds == null) return "--:--";
  const s = Math.floor(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// What each sport is tagged on. A new sport with event types needs a surface here.
const SURFACES: Record<string, { title: string; pick: string }> = {
  football: { title: "Where on the pitch (attacking to the right)", pick: "Click the pitch where it happened." },
  table_tennis: {
    title: "Where the deciding ball landed (the player's side on the left)",
    pick: "Click the table where the deciding ball landed.",
  },
};

export default function TagMatchPage() {
  const [modules, setModules] = useState<SportModule[]>([]);
  const [sport, setSport] = useState("football");
  const [allPlayers, setAllPlayers] = useState<SquadRow[]>([]);
  // Today where the coach is. toISOString would give the UTC date, which in Cairo is still
  // yesterday for the first hours after midnight.
  const [matchDate, setMatchDate] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  });
  const [matchLabel, setMatchLabel] = useState("");
  const [playerId, setPlayerId] = useState("");
  const [video, setVideo] = useState<string | null>(null);
  const [point, setPoint] = useState<{ x: number; y: number } | null>(null);
  const [kind, setKind] = useState<EventType | null>(null);
  const [tags, setTags] = useState<MatchTags | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    getSports()
      .then((all) => setModules(all.filter((s) => s.events.length > 0 && SURFACES[s.sport])))
      .catch((e) => setError(e.message));
    getSquad()
      .then(setAllPlayers)
      .catch((e) => setError(e.message));
  }, []);

  // Sports this club has players in and that can be tagged. A table tennis academy opens on
  // table tennis.
  const sports = useMemo(
    () => modules.filter((m) => allPlayers.some((r) => r.player.primarySport === m.sport)),
    [modules, allPlayers],
  );
  useEffect(() => {
    if (sports.length > 0 && !sports.some((m) => m.sport === sport)) setSport(sports[0].sport);
  }, [sports, sport]);
  // Memoised so the keyboard handler below is not removed and added again on every render.
  const types: EventType[] | null = useMemo(
    () => (modules.length ? modules.find((m) => m.sport === sport)?.events ?? [] : null),
    [modules, sport],
  );
  const squad = allPlayers.filter((r) => r.player.primarySport === sport);

  const refresh = useCallback(() => {
    if (!matchDate) return;
    getMatchTags(matchDate, matchLabel)
      .then(setTags)
      .catch((e) => setError(e.message));
  }, [matchDate, matchLabel]);
  useEffect(refresh, [refresh]);

  // The object URL is the coach's own file in this tab; it is released when replaced.
  useEffect(() => () => {
    if (video) URL.revokeObjectURL(video);
  }, [video]);

  const colourOf = useMemo(() => {
    const map: Record<string, string> = {};
    (types ?? []).forEach((t, i) => (map[t.key] = FIXED_COLOURS[t.key] ?? TYPE_COLOURS[i % TYPE_COLOURS.length]));
    return map;
  }, [types]);

  const save = useCallback(
    async (outcome: string) => {
      if (!kind || !point || !playerId) return;
      setSaving(true);
      setError(null);
      try {
        await tagEvent({
          playerId,
          matchDate,
          matchLabel: matchLabel.trim() || null,
          eventType: kind.key,
          outcome,
          x: point.x,
          y: point.y,
          videoSeconds: videoRef.current && video ? Math.round(videoRef.current.currentTime * 10) / 10 : null,
        });
        setPoint(null);
        setKind(null);
        refresh();
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setSaving(false);
      }
    },
    [kind, point, playerId, matchDate, matchLabel, video, refresh],
  );

  // Keys, unless the coach is typing in a field: space plays or pauses, arrows skip five
  // seconds, a type's key picks the type, a number picks the outcome, Esc starts again.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
      const v = videoRef.current;
      if (e.key === " " && v) {
        e.preventDefault();
        if (v.paused) void v.play();
        else v.pause();
      } else if (e.key === "ArrowLeft" && v) {
        v.currentTime = Math.max(0, v.currentTime - 5);
      } else if (e.key === "ArrowRight" && v) {
        v.currentTime = v.currentTime + 5;
      } else if (e.key === "Escape") {
        setPoint(null);
        setKind(null);
      } else if (point && !kind) {
        const t = types?.find((t) => t.shortcut === e.key.toLowerCase());
        if (t) setKind(t);
      } else if (point && kind && /^[1-9]$/.test(e.key)) {
        const o = kind.outcomes[Number(e.key) - 1];
        if (o) void save(o.key);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [point, kind, types, save]);

  const markers: PitchMarker[] = [
    ...(tags?.events ?? [])
      // Only this sport's events: a club tagging both sports on one date sees each on its own surface.
      .filter((e) => e.x != null && e.y != null && colourOf[e.eventType])
      .map((e) => ({
        id: e.id,
        x: e.x as number,
        y: e.y as number,
        colour: colourOf[e.eventType] ?? "#94a3b8",
        label: `${clock(e.videoSeconds)} ${e.playerName ?? ""}: ${e.eventType}, ${e.outcome}`,
      })),
    ...(point ? [{ id: "new", x: point.x, y: point.y, colour: "#f8fafc", label: "new tag", selected: true }] : []),
  ];

  const onPick = (x: number, y: number) => {
    videoRef.current?.pause();
    setPoint({ x, y });
    setKind(null);
  };

  const players = tags?.players ?? [];
  const totals = Array.from(new Set(players.flatMap((p) => Object.keys(p.tagged))));
  const typeLabel = (key: string) => types?.find((t) => t.key === key)?.label ?? key;
  const outcomeLabel = (type: string, key: string) =>
    types?.find((t) => t.key === type)?.outcomes.find((o) => o.key === key)?.label ?? key;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Tag a match</h1>
        <p className="text-sm text-slate-400">
          Play the match video, click where something happened, then pick what it was. The video
          stays on your device; only the tags are saved.
        </p>
      </div>

      {error ? <Banner tone="warn">{error}</Banner> : null}

      <Card>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Field label="Match date">
            <input className={inputClass} type="date" value={matchDate} onChange={(e) => setMatchDate(e.target.value)} />
          </Field>
          <Field label="Match" hint="Your own name for it, for example vs Zamalek U15">
            <input
              className={inputClass}
              value={matchLabel}
              maxLength={80}
              placeholder="vs ..."
              onChange={(e) => setMatchLabel(e.target.value)}
            />
          </Field>
          <Field label="Video">
            <input
              className={inputClass}
              type="file"
              accept="video/*"
              aria-label="Match video"
              onChange={(e) => {
                const file = e.target.files?.[0];
                setVideo(file ? URL.createObjectURL(file) : null);
              }}
            />
          </Field>
          {sports.length > 1 ? (
            <Field label="Sport">
              <select
                className={inputClass}
                value={sport}
                onChange={(e) => {
                  setSport(e.target.value);
                  setPlayerId("");
                  setPoint(null);
                  setKind(null);
                }}
              >
                {sports.map((m) => (
                  <option key={m.sport} value={m.sport}>
                    {m.label}
                  </option>
                ))}
              </select>
            </Field>
          ) : null}
          <Field label="Player">
            <select className={inputClass} value={playerId} onChange={(e) => setPlayerId(e.target.value)}>
              <option value="">Choose a player</option>
              {squad.map((r) => (
                <option key={r.player.id} value={r.player.id}>
                  {r.player.fullName} {r.player.position ? `(${r.player.position})` : ""}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          {video ? (
            <video ref={videoRef} src={video} controls className="w-full rounded bg-black" />
          ) : (
            <p className="text-sm text-slate-500">
              Choose a video file above. Without one you can still tag, but the tags will have no
              video time to check them against.
            </p>
          )}
          <p className="mt-2 text-xs text-slate-500">
            Keys: space plays or pauses, the arrows skip 5 seconds, Esc cancels a tag.
          </p>
        </Card>

        <Card>
          <SectionTitle>{SURFACES[sport]?.title}</SectionTitle>
          {sport === "table_tennis" ? (
            <TennisTable markers={markers} onPick={onPick} />
          ) : (
            <Pitch markers={markers} onPick={onPick} />
          )}
          <div className="mt-3 min-h-[5.5rem]">
            {!playerId ? (
              <p className="text-sm text-slate-500">Choose the player first.</p>
            ) : !point ? (
              <p className="text-sm text-slate-500">{SURFACES[sport]?.pick}</p>
            ) : !kind ? (
              <div className="flex flex-wrap gap-2">
                {(types ?? []).map((t) => (
                  <Button key={t.key} onClick={() => setKind(t)}>
                    {t.label} <span className="ml-1 text-xs text-slate-500">{t.shortcut}</span>
                  </Button>
                ))}
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-slate-300">{kind.label}:</span>
                {kind.outcomes.map((o, i) => (
                  <Button key={o.key} variant="primary" disabled={saving} onClick={() => void save(o.key)}>
                    {o.label} <span className="ml-1 text-xs opacity-70">{i + 1}</span>
                  </Button>
                ))}
                <Button variant="ghost" onClick={() => setKind(null)}>
                  Back
                </Button>
              </div>
            )}
          </div>
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <SectionTitle>
            Tags {tags ? `(${tags.events.length})` : ""}
          </SectionTitle>
          {!tags || tags.events.length === 0 ? (
            <p className="text-sm text-slate-500">Nothing tagged for this match yet.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-slate-800 text-sm">
              {tags.events.map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-3 py-1.5">
                  <button
                    className={cx("w-14 shrink-0 text-left tabular-nums", e.videoSeconds != null && video ? "text-sky-300 hover:underline" : "text-slate-500")}
                    disabled={e.videoSeconds == null || !video}
                    onClick={() => {
                      if (videoRef.current && e.videoSeconds != null) videoRef.current.currentTime = e.videoSeconds;
                    }}
                    title="Go to this moment in the video"
                  >
                    {clock(e.videoSeconds)}
                  </button>
                  <span className="min-w-0 flex-1 truncate" dir="auto">
                    {e.playerName}
                  </span>
                  <span className="shrink-0 text-slate-300">
                    <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: colourOf[e.eventType] }} />
                    {typeLabel(e.eventType)}, {outcomeLabel(e.eventType, e.outcome).toLowerCase()}
                  </span>
                  <button
                    className="shrink-0 text-xs text-slate-500 hover:text-rose-300"
                    onClick={() => untagEvent(e.id).then(refresh).catch((err) => setError(err.message))}
                    aria-label={`Remove the ${typeLabel(e.eventType)} at ${clock(e.videoSeconds)}`}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <SectionTitle>Tagged against logged</SectionTitle>
          {players.length === 0 ? (
            <p className="text-sm text-slate-500">Each player you tag appears here.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="text-[0.66rem] uppercase tracking-[0.1em] text-slate-500">
                    <th className="border-b border-slate-700 px-2 py-2 text-left">Player</th>
                    {totals.map((t) => (
                      <th key={t} className="border-b border-slate-700 px-2 py-2 text-right">
                        {t.replace(/_/g, " ")}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {players.map((p) => (
                    <tr key={p.playerId}>
                      <td className="border-b border-slate-800/70 px-2 py-2" dir="auto">
                        {p.playerName}
                      </td>
                      {totals.map((t) => {
                        const tagged = p.tagged[t] ?? 0;
                        const logged = p.logged ? p.logged[t] : null;
                        const differs = logged != null && logged !== tagged;
                        return (
                          <td
                            key={t}
                            className={cx("border-b border-slate-800/70 px-2 py-2 text-right tabular-nums", differs && "text-amber-300")}
                          >
                            {tagged}
                            <span className="text-slate-500"> / {logged ?? "-"}</span>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="mt-2 text-xs text-slate-500">
            Tagged / logged for this date. Amber where they differ; a dash where no match record
            was logged for the player that day.
          </p>
        </Card>
      </div>
    </div>
  );
}
