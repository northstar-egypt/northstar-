"use client";

/**
 * The player's home: their own journey, written to them rather than about them. Every other role
 * opens on a list of players; a player used to open on the screen scouts read about them.
 *
 * It compares a player with their own past and says plainly who can see their record. It carries
 * no verdicts or model flags: those are claims about a player that they have no route to dispute
 * yet, and the API keeps them from a player's own view. Nothing here needs an endpoint of its own:
 * it is the player's profile and league seasons, which the API already scopes to them.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { GrowthChart, ShareRange } from "@/components/charts";
import { Avatar, Banner, Button, Card, Chip, SectionTitle, Skeleton } from "@/components/ui";
import { getProSeasons, getProfile } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cx, shortDate } from "@/lib/format";
import { ROLE_IDENTITY } from "@/lib/roles";
import type { PlayerProfile, ProSeasons, SummaryStat } from "@/lib/types";

const me = ROLE_IDENTITY.player;
const pct = (x: number) => `${Math.round(x * 100)}%`;

function formatStat(stat: SummaryStat): string {
  return stat.format === "percent" ? pct(stat.value) : stat.value.toFixed(2);
}

const CONSENT_WORDS: Record<string, { label: string; means: string }> = {
  data_storage: { label: "Keeping your record", means: "NorthStar stores your details and numbers." },
  analytics: {
    label: "Analysing your numbers",
    means: "Your numbers are compared with other players', and the models run on them.",
  },
  scouting_visibility: { label: "Being seen by scouts", means: "Scouts can find you and open your record." },
};

export default function PlayerHomePage() {
  const { user } = useAuth();
  const playerId = user?.linkedPlayerId ?? null;
  const [profile, setProfile] = useState<PlayerProfile | null | "missing">(null);
  const [seasons, setSeasons] = useState<ProSeasons | null>(null);

  useEffect(() => {
    if (!playerId) return;
    let alive = true;
    getProfile(playerId).then((p) => {
      if (alive) setProfile(p && !("mergedInto" in p) ? p : "missing");
    });
    getProSeasons(playerId)
      .then((s) => alive && setSeasons(s))
      .catch(() => alive && setSeasons(null));
    return () => {
      alive = false;
    };
  }, [playerId]);

  if (!playerId || profile === "missing") {
    return (
      <Banner tone="info" title="No record linked to your account">
        Your account is not linked to a player record yet. Your coach or the federation can link it.
      </Banner>
    );
  }
  if (profile === null) return <Skeleton className="h-96" />;

  const p = profile.player;
  const measured = profile.growth.measured;
  const lastMeasured = measured.length ? measured[measured.length - 1].date : null;
  const leagueSeasons = seasons?.seasons ?? [];
  const trend = seasons?.trends[0] ?? null;
  const rating = profile.rating;
  const numbers = profile.performance.filter((s) => s.known && s.summary.length > 0);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-4">
        <Avatar size={72} name={p.fullName} />
        <div className="min-w-[14rem] flex-1">
          <h1 className={cx("text-3xl font-bold tracking-tight", me.text)}>
            {me.greeting(p.fullName.split(" ")[0] ?? null)}
          </h1>
          <p className="mt-1 text-slate-400">{me.tagline}</p>
          <p className="text-sm text-slate-500">
            {[profile.organizationName, p.position?.replace(/_/g, " "), `age ${profile.ageLabel}`]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <Link href={`/players/${p.id}`}>
          <Button variant="ghost">See your full record</Button>
        </Link>
      </div>

      {trend ? (
        <Card className={cx("border-l-4", me.border)}>
          <h2 className="text-lg font-semibold">You against last season</h2>
          <p className="mb-3 text-sm text-slate-400">
            {trend.previous} to {trend.season}: {trend.minutesBefore.toLocaleString()} minutes, then{" "}
            {trend.minutesAfter.toLocaleString()}. Only you are in this comparison.
          </p>
          <ul className="grid gap-x-8 gap-y-1.5 text-sm sm:grid-cols-2">
            {trend.changes.map((c) => {
              const sign = c.unit === "%" ? "%" : "";
              return (
                <li key={c.key} className="flex items-baseline justify-between gap-3">
                  <span className="text-slate-300">{c.label}</span>
                  <span className="tabular-nums text-slate-400">
                    {c.before}
                    {sign} to{" "}
                    <span className={cx("font-semibold", c.after > c.before ? me.text : "text-slate-200")}>
                      {c.after}
                      {sign}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        </Card>
      ) : null}

      {leagueSeasons.length > 0 ? (
        <Card>
          <SectionTitle>Your league seasons</SectionTitle>
          <ul className="flex flex-col divide-y divide-slate-800">
            {leagueSeasons.map((s) => (
              <li key={`${s.season}-${s.competition}`} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2">
                <span className="font-semibold text-slate-100">
                  {s.season}
                  <span className="ml-2 text-xs font-normal text-slate-500">
                    {[s.club, s.competition].filter(Boolean).join(", ")}
                  </span>
                </span>
                <span className="text-sm tabular-nums text-slate-400">
                  {s.minutes.toLocaleString()} minutes, {s.finishing.npGoals} goals without penalties
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {rating ? (
        <Card className={cx(!trend && "border-l-4", !trend && me.border)}>
          <h2 className="text-lg font-semibold">Your strength</h2>
          {rating.shown && rating.pointShare != null && rating.low != null && rating.high != null ? (
            <div className="mt-2 flex flex-col gap-3">
              <p className="text-slate-200">
                <span className={cx("text-2xl font-bold tabular-nums", me.text)}>{pct(rating.pointShare)}</span> of points
                against an average opponent, likely between {pct(rating.low)} and {pct(rating.high)}.
              </p>
              <ShareRange value={rating.pointShare} low={rating.low} high={rating.high} />
              <p className="text-xs text-slate-500">
                From {rating.ratedMatches} rated match{rating.ratedMatches === 1 ? "" : "es"}, among {rating.population}.
                The range narrows as you play more.
              </p>
            </div>
          ) : (
            <p className="mt-1 text-sm text-slate-400">{rating.note}</p>
          )}
        </Card>
      ) : null}

      {numbers.length > 0 ? (
        <Card>
          <SectionTitle>Your numbers</SectionTitle>
          <div className="flex flex-col gap-4">
            {numbers.map((section) => (
              <div key={section.schemaRef}>
                <p className="mb-2 text-sm font-semibold text-slate-200">{section.label}</p>
                <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {section.summary.map((stat) => (
                    <div key={stat.key}>
                      <dt className="text-xs text-slate-500">{stat.label}</dt>
                      <dd className="text-lg font-semibold tabular-nums">{formatStat(stat)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {/* A child's growth is the story; an adult's height has stopped changing. */}
      {p.isMinor ? (
        <Card>
          <SectionTitle>How you are growing</SectionTitle>
          <GrowthChart series={profile.growth} />
          <p className="mt-2 text-sm text-slate-400">
            Everyone grows on their own timetable. Being shorter than others your age says nothing about how good you
            will be.
          </p>
        </Card>
      ) : null}

      <div className="grid gap-5 md:grid-cols-2">
        <Card>
          <SectionTitle>On your record</SectionTitle>
          <ul className="flex flex-col gap-1.5 text-sm text-slate-300">
            <li>
              {profile.latest.heightCm ? `${profile.latest.heightCm} cm` : "No height yet"}
              {profile.latest.weightKg ? `, ${profile.latest.weightKg} kg` : ""}
              {lastMeasured ? `, last measured ${shortDate(lastMeasured)}` : ""}
            </li>
            <li>{profile.provenance.measurementCount} measurements</li>
            <li>{profile.provenance.performanceCount} performance records</li>
          </ul>
          <p className="mt-3 text-xs text-slate-500">
            Something wrong? Ask whoever logged it, usually your coach.
          </p>
        </Card>

        <Card>
          <SectionTitle>Who can see your record</SectionTitle>
          <ul className="flex flex-col gap-1.5 text-sm text-slate-300">
            <li>
              {profile.organizationName ? (
                <>
                  <span className="font-semibold text-slate-100">Coaches at {profile.organizationName}</span>: yes
                </>
              ) : (
                <>
                  <span className="font-semibold text-slate-100">Coaches</span>: none, as you are not registered with a
                  club
                </>
              )}
            </li>
            <li>
              <span className="font-semibold text-slate-100">Federation staff</span>: yes
            </li>
            <li>
              <span className="font-semibold text-slate-100">Scouts</span>:{" "}
              {p.isMinor
                ? "only while your guardian's consent is in effect"
                : "yes. Adult players are visible to scouts, whatever the setting below says"}
            </li>
            <li>
              <span className="font-semibold text-slate-100">Other players</span>: no
            </li>
          </ul>
        </Card>
      </div>

      <Card>
        <SectionTitle>What you have agreed to</SectionTitle>
        <ul className="flex flex-col gap-3">
          {profile.provenance.consents.map((c) => {
            const words = CONSENT_WORDS[c.purpose];
            return (
              <li key={c.purpose} className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-slate-100">{words?.label ?? c.purpose.replace(/_/g, " ")}</p>
                  {words ? <p className="text-xs text-slate-500">{words.means}</p> : null}
                </div>
                <Chip tone={c.granted ? "good" : "warn"}>{c.granted ? "agreed" : "not agreed"}</Chip>
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-sm text-slate-400">
          You can withdraw at any time from{" "}
          <Link href={`/players/${p.id}`} className="text-sky-300 hover:underline">
            your full record
          </Link>
          . It takes effect at once.
        </p>
      </Card>
    </div>
  );
}
