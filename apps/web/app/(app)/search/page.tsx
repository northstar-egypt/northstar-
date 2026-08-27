"use client";

/**
 * Scout search. See docs/wireframes/05-scout-search.html.
 *
 * Two ways to ask the same question, and the screen has to make them feel like one tool. The
 * element that makes that work is the interpretation strip: it shows what the sentence was
 * turned into, so a scout can tell a real absence of results from a misread query.
 *
 * The natural language half needs embeddings, which the ML track deferred until they pick a
 * model. The filter half does not, so it is written to work first and the sentence box is
 * clearly marked as the part that is not real yet.
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
import { search } from "@/lib/api";
import { pct } from "@/lib/format";
import type { ParsedQuery, SearchResult } from "@/lib/types";

const TIERS = ["pro", "youth", "diaspora"] as const;

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [tier, setTier] = useState<string | null>("youth");
  const [position, setPosition] = useState("");
  const [egyptOnly, setEgyptOnly] = useState(false);
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [parsed, setParsed] = useState<ParsedQuery>({ chips: [] });
  const [busy, setBusy] = useState(false);

  async function run(q: string) {
    setBusy(true);
    const res = await search(q, { tier, position, egyptOnly });
    setResults(res.results);
    setParsed(res.parsed);
    setSubmitted(q);
    setBusy(false);
  }

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
              Or use the filters. They work on their own.
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
          <p className="mt-2 text-xs text-slate-500">
            Amber means the system has no data for that part of the request rather than that
            nothing matched. Without this strip you cannot tell those two apart.
          </p>
        </Card>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[13rem_1fr]">
        <Card className="h-fit">
          <SectionTitle>Filters</SectionTitle>
          <div className="flex flex-col gap-3.5">
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

            <div className="flex flex-col gap-1">
              <Label>Position</Label>
              <input
                value={position}
                onChange={(e) => setPosition(e.target.value)}
                placeholder="ST"
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
            <Empty>No players match. Try widening the filters.</Empty>
          ) : (
            <>
              <div className="flex items-center justify-between">
                <span className="text-xs uppercase tracking-[0.12em] text-slate-500">
                  {results.length} players
                </span>
                <span className="text-xs text-slate-600">sorted by relevance</span>
              </div>

              {results.map((r) => (
                <Card key={r.player.id} className={r.withheld ? "border-dashed" : undefined}>
                  <div className="flex flex-wrap items-start gap-3">
                    <Avatar size={44} />
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
                        <Chip tone={r.matchScore > 0.9 ? "brand" : "default"} title="Similarity score, not a probability.">
                          {pct(r.matchScore)} match
                        </Chip>
                      </div>

                      <span className="text-xs text-slate-500">
                        {r.organizationName} &middot; {r.player.position} &middot; {r.ageLabel}
                        {r.heightCm ? ` · ${r.heightCm} cm` : ""}
                      </span>

                      {r.withheld ? (
                        <Banner tone="warn">
                          {r.withheldReason}{" "}
                          <span className="underline decoration-dotted">
                            Request access through the academy
                          </span>
                          <p className="mt-1 text-xs text-slate-500">
                            Whether a withheld player should appear at all is an open question.
                            Showing the card lets a scout chase consent. Hiding it leaks less.
                          </p>
                        </Banner>
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
