"use client";

/**
 * Scout search. See docs/wireframes/05-scout-search.html.
 *
 * Two ways to ask the same question, and the screen has to make them feel like one tool. The
 * element that makes that work is the interpretation strip: it shows what the sentence was
 * turned into, so a scout can tell a real absence of results from a misread query.
 *
 * The sentence box is read on the server (apps/api/app/services/search.py): patterns become
 * filters, phrases are read as things the platform computes (app/concepts.py, with a local
 * embedding model), and the rest as names in Arabic or Latin spelling. The chips say which,
 * and an amber chip changed nothing.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { Sparkline } from "@/components/charts";
import {
  Avatar,
  Banner,
  Button,
  Card,
  Chip,
  Empty,
  Label,
  SectionTitle,
  Skeleton,
  inputClass,
} from "@/components/ui";
import { getSports, search } from "@/lib/api";
import { pct } from "@/lib/format";
import type { ParsedQuery, SearchResult, SportModule } from "@/lib/types";

const TIERS = ["pro", "youth", "diaspora"] as const;

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [tier, setTier] = useState<string | null>("youth");
  const [position, setPosition] = useState("");
  const [egyptOnly, setEgyptOnly] = useState(false);
  // Sport and gender come from the sport modules. A sport open to boys and girls (table tennis)
  // is searched one gender at a time, the same way every comparison in the platform keeps them
  // apart; football registers boys only, so it never asks.
  const [sports, setSports] = useState<SportModule[]>([]);
  const [sport, setSport] = useState<string | null>(null);
  const [sex, setSex] = useState<"male" | "female" | null>(null);
  const sportModule = sports.find((m) => m.sport === sport) ?? null;
  const usesTier = sportModule ? sportModule.usesTier : true;
  const asksSex = (sportModule?.genders.length ?? 0) > 1;
  const [results, setResults] = useState<SearchResult[] | null>(null);
  // Players ticked for comparison, kept across new searches so a scout can gather them.
  const [picked, setPicked] = useState<string[]>([]);
  const togglePick = (id: string) =>
    setPicked((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : ids.length < 4 ? [...ids, id] : ids));
  const [parsed, setParsed] = useState<ParsedQuery>({ chips: [] });
  const [busy, setBusy] = useState(false);
  // The filters in force, in words, for an empty result: "youth tier" was on by default and
  // nothing said so, so a search for a pro player found nobody and said "widen the filters".
  const activeFilters = [
    usesTier && tier ? `${tier} tier` : null,
    position ? `position ${position}` : null,
    egyptOnly ? "Egypt eligible only" : null,
    sport ? (sportModule?.label ?? sport) : null,
    asksSex && sex ? (sex === "female" ? "girls" : "boys") : null,
  ].filter((item): item is string => item !== null);

  // `clear` re-runs with filters taken off, for the buttons in an empty result.
  async function run(q: string, clear: { tier?: boolean; all?: boolean } = {}) {
    setBusy(true);
    if (clear.tier || clear.all) setTier(null);
    if (clear.all) {
      setPosition("");
      setEgyptOnly(false);
      setSport(null);
      setSex(null);
    }
    const res = await search(q, {
      tier: usesTier && !clear.tier && !clear.all ? tier : null,
      position: clear.all ? "" : position,
      egyptOnly: clear.all ? false : egyptOnly,
      sport: clear.all ? null : sport,
      sex: asksSex && !clear.all ? sex : null,
    });
    setResults(res.results);
    setParsed(res.parsed);
    setSubmitted(q);
    setBusy(false);
  }

  useEffect(() => {
    getSports()
      .then(setSports)
      .catch(() => setSports([]));
  }, []);

  useEffect(() => {
    run("");
    // Runs once on mount to populate the default list. Filters re-run explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col gap-5">
      <h1 className="text-xl font-bold tracking-tight">Search</h1>

      <Card>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(query);
          }}
          className="flex flex-col gap-3"
        >
          <Label>Describe what you are looking for</Label>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="left footed striker under 16, small for his age but scoring well"
            className={inputClass}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs text-slate-500">
              Describe players in words, or type a name in Arabic or English. Or use the
              filters. They work on their own.
            </span>
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? "Searching" : "Search"}
            </Button>
          </div>
        </form>
      </Card>

      {/* The most important element on this screen: what the sentence was understood to mean. */}
      {submitted && parsed.chips.length > 0 ? (
        <Card className="bg-slate-900/40">
          <SectionTitle>How this was read</SectionTitle>
          <div className="flex flex-wrap gap-1.5">
            {parsed.chips.map((c) => (
              <Chip key={c.label} tone={c.understood ? "brand" : "warn"}>
                {c.label}
              </Chip>
            ))}
          </div>
          {parsed.chips.some((c) => !c.understood) ? (
            <p className="mt-2 text-xs text-slate-500">
              Amber parts did not change the results: the platform has no data for them, or they
              are not something search can do.
            </p>
          ) : null}
        </Card>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[13rem_1fr]">
        <Card className="h-fit">
          <SectionTitle>Filters</SectionTitle>
          <div className="flex flex-col gap-3.5">
            {sports.length > 1 ? (
              <div className="flex flex-col gap-1.5">
                <Label>Sport</Label>
                <div className="flex flex-wrap gap-1.5">
                  {sports.map((m) => (
                    <Chip
                      key={m.sport}
                      onClick={() => {
                        setSport(sport === m.sport ? null : m.sport);
                        setSex(null);
                      }}
                      active={sport === m.sport}
                    >
                      {m.label}
                    </Chip>
                  ))}
                </div>
              </div>
            ) : null}

            {asksSex ? (
              <div className="flex flex-col gap-1.5">
                <Label>Boys or girls</Label>
                <div className="flex gap-1.5">
                  <Chip onClick={() => setSex(sex === "male" ? null : "male")} active={sex === "male"}>
                    boys
                  </Chip>
                  <Chip
                    onClick={() => setSex(sex === "female" ? null : "female")}
                    active={sex === "female"}
                  >
                    girls
                  </Chip>
                </div>
              </div>
            ) : null}

            {usesTier ? (
            <div className="flex flex-col gap-1.5">
              <Label>Tier</Label>
              <div className="flex flex-wrap gap-1.5">
                {TIERS.map((t) => (
                  <Chip
                    key={t}
                    onClick={() => setTier(tier === t ? null : t)}
                    active={tier === t}
                  >
                    {t}
                  </Chip>
                ))}
              </div>
            </div>
            ) : null}

            <div className="flex flex-col gap-1">
              <Label>Position</Label>
              <input
                value={position}
                onChange={(e) => setPosition(e.target.value)}
                placeholder="any, e.g. ST"
                className={inputClass}
              />
            </div>

            <label className="flex items-center justify-between gap-2">
              <span className="text-sm text-slate-300">Egypt eligible only</span>
              <input
                type="checkbox"
                checked={egyptOnly}
                onChange={(e) => setEgyptOnly(e.target.checked)}
                className="h-4 w-4 accent-sky-500"
              />
            </label>

            <div className="flex gap-2">
              <Button size="sm" onClick={() => run(query)} disabled={busy}>
                Apply
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setTier(null);
                  setSport(null);
                  setSex(null);
                  setPosition("");
                  setEgyptOnly(false);
                  setQuery("");
                  run("");
                }}
              >
                Reset
              </Button>
            </div>
          </div>
        </Card>

        <div className="flex flex-col gap-3">
          {!results ? (
            <>
              <Skeleton className="h-24" />
              <Skeleton className="h-24" />
            </>
          ) : results.length === 0 ? (
            <Empty>
              <p>No players match{submitted ? ` "${submitted}"` : ""}.</p>
              {activeFilters.length ? (
                <>
                  <p className="mt-1">Filters on: {activeFilters.join(", ")}.</p>
                  <div className="mt-3 flex flex-wrap justify-center gap-2">
                    {usesTier && tier ? (
                      <Button size="sm" onClick={() => run(submitted, { tier: true })}>
                        Search every tier
                      </Button>
                    ) : null}
                    <Button size="sm" variant="ghost" onClick={() => run(submitted, { all: true })}>
                      Clear all filters
                    </Button>
                  </div>
                </>
              ) : null}
            </Empty>
          ) : (
            <>
              <div className="flex items-center justify-between">
                <span className="text-xs uppercase tracking-[0.12em] text-slate-500">
                  {results.length} {results.length === 1 ? "player" : "players"}
                  {usesTier && tier ? `, ${tier} tier only` : ""}
                </span>
                <span className="text-xs text-slate-600">sorted by relevance</span>
              </div>

              {picked.length > 0 ? (
                <Card className="flex flex-wrap items-center justify-between gap-2 border-sky-800">
                  <span className="text-sm text-slate-300">
                    {picked.length} of up to 4 picked to compare
                    {picked.length < 2 ? ": pick at least one more" : ""}
                  </span>
                  <span className="flex gap-2">
                    <button className="text-xs text-slate-500 hover:text-slate-300" onClick={() => setPicked([])}>
                      Clear
                    </button>
                    {picked.length >= 2 ? (
                      <Link
                        href={`/compare?players=${picked.map(encodeURIComponent).join(",")}`}
                        className="rounded-md bg-sky-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-sky-500"
                      >
                        Compare {picked.length}
                      </Link>
                    ) : null}
                  </span>
                </Card>
              ) : null}

              {results.map((r) => (
                <Card key={r.player.id} className={r.withheld ? "border-dashed" : undefined}>
                  <div className="flex flex-wrap items-start gap-3">
                    <Avatar size={44} name={r.withheld ? null : r.player.fullName} />
                    <div className="flex min-w-[12rem] flex-1 flex-col gap-1.5">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        {r.withheld ? (
                          <span className="font-semibold text-slate-400">{r.player.fullName}</span>
                        ) : (
                          <Link
                            href={`/players/${r.player.id}`}
                            className="font-semibold text-slate-100 hover:text-sky-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
                          >
                            {r.player.fullName}
                          </Link>
                        )}
                        <span className="flex items-center gap-2">
                          {!r.withheld ? (
                            <label className="flex cursor-pointer items-center gap-1 text-xs text-slate-400">
                              <input
                                type="checkbox"
                                checked={picked.includes(r.player.id)}
                                disabled={!picked.includes(r.player.id) && picked.length >= 4}
                                onChange={() => togglePick(r.player.id)}
                                aria-label={`Pick ${r.player.fullName} to compare`}
                              />
                              compare
                            </label>
                          ) : null}
                          {/* Every result of a filter-only search scores 100%, which says nothing. */}
                          {r.matchScore < 0.995 ? (
                            <Chip tone={r.matchScore > 0.9 ? "brand" : "default"} title="Similarity score, not a probability.">
                              {pct(r.matchScore)} match
                            </Chip>
                          ) : null}
                        </span>
                      </div>

                      <span className="text-xs text-slate-500">
                        {[
                          r.organizationName,
                          r.player.position,
                          r.ageLabel,
                          r.heightCm ? `${r.heightCm} cm` : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>

                      {r.withheld ? (
                        <Banner tone="warn">{r.withheldReason}</Banner>
                      ) : (
                        <div className="flex flex-wrap items-center gap-1.5">
                          {r.highlights.map((h) => (
                            <Chip key={h}>{h}</Chip>
                          ))}
                          {r.trend.length > 1 ? <Sparkline values={r.trend} /> : null}
                        </div>
                      )}
                    </div>
                  </div>
                </Card>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
