"use client";

/**
 * Import table tennis results from a spreadsheet. Federation staff and admins.
 * See apps/api/app/services/results_import.py and docs/results-import.md.
 *
 * The results come from the official ITTF and WTT sites, read and copied by a person: those
 * sites refuse automated access, so there is no scraper. One row is one match: the date, the
 * event, the two players and the game scores. Sets, points and "best of" are worked out from
 * the scores. Three steps as for players, and nothing is saved until Import.
 */

import Link from "next/link";
import { useState } from "react";
import { Banner, Button, Card, Chip, SectionTitle } from "@/components/ui";
import { importResults, previewResults } from "@/lib/api";
import type { ResultsImport } from "@/lib/types";

const TEMPLATE_COLUMNS: [string, string][] = [
  ["date", "YYYY-MM-DD (required)"],
  ["event", "the event, e.g. WTT Youth Contender 2026"],
  ["player_a", "one player's name as published (required)"],
  ["player_b", "the other player's name (required)"],
  ["games", "game scores from player A's side: 11-7, 9-11, 11-5, 11-8 (required)"],
  ["best_of", "3, 5 or 7; worked out from the scores when empty"],
  ["player_a_id", "player A's NorthStar id, when the name matches several players"],
  ["player_b_id", "player B's NorthStar id"],
];

const TONE = { ready: "good", imported: "good", duplicate: "warn", rejected: "bad" } as const;

function downloadTemplate() {
  // Column names only, built here, so there is no template file that could ever hold real data.
  const blob = new Blob([TEMPLATE_COLUMNS.map(([name]) => name).join(",") + "\n"], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "northstar-results-template.csv";
  link.click();
  URL.revokeObjectURL(url);
}

export default function ImportResultsPage() {
  const [text, setText] = useState<string | null>(null);
  const [fileName, setFileName] = useState("");
  const [result, setResult] = useState<ResultsImport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function choose(file: File | undefined) {
    setResult(null);
    setError(null);
    if (!file) return;
    setFileName(file.name);
    const content = await file.text();
    setText(content);
    setBusy(true);
    try {
      setResult(await previewResults(content));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runImport() {
    if (text === null) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await importResults(text));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const ready = result && !result.saved ? result.rows.filter((r) => r.status === "ready").length : 0;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Import table tennis results</h1>
        <p className="text-sm text-slate-500">
          Match results copied from the official ITTF or WTT results, saved as CSV. Nothing is
          saved until you press Import.
        </p>
      </div>

      <Card>
        <SectionTitle>1. Choose a file</SectionTitle>
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="file"
            accept=".csv,text/csv"
            aria-label="CSV file"
            onChange={(e) => choose(e.target.files?.[0])}
            className="text-sm text-slate-300 file:mr-3 file:rounded-md file:border-0 file:bg-slate-800 file:px-3 file:py-2 file:text-slate-100"
          />
          <Button variant="ghost" onClick={downloadTemplate}>
            Download the template
          </Button>
        </div>
        <details className="mt-3 text-xs text-slate-400">
          <summary className="cursor-pointer">What the columns mean</summary>
          <ul className="mt-2 grid gap-1 sm:grid-cols-2">
            {TEMPLATE_COLUMNS.map(([name, meaning]) => (
              <li key={name}>
                <code className="text-slate-300">{name}</code>: {meaning}
              </li>
            ))}
          </ul>
        </details>
        <p className="mt-3 text-xs text-slate-500">
          Names are matched to registered players in Arabic or Latin spelling. A player who is not
          on NorthStar is not stored at all; their opponent&apos;s record still is. Importing a
          file twice is safe: matches already on record are skipped.
        </p>
      </Card>

      {error ? <Banner tone="bad" title="Not done">{error}</Banner> : null}
      {busy ? <p className="text-sm text-slate-400">Checking every match...</p> : null}

      {result && result.fileProblems.length > 0 ? (
        <Banner tone="bad" title={`${fileName} could not be read`}>
          <ul className="list-disc pl-4">
            {result.fileProblems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Banner>
      ) : null}

      {result && result.rows.length > 0 ? (
        <Card>
          <SectionTitle>{result.saved ? "3. Imported" : `2. Check every match in ${fileName}`}</SectionTitle>
          <div className="mb-3 flex flex-wrap gap-2">
            {Object.entries(result.counts).map(([status, n]) => (
              <Chip key={status} tone={TONE[status as keyof typeof TONE] ?? "default"}>
                {n} {status}
              </Chip>
            ))}
            {result.saved ? <Chip>{result.recordsWritten} match records written</Chip> : null}
          </div>
          <ul className="flex flex-col divide-y divide-slate-800">
            {result.rows.map((row) => (
              <li key={row.line} className="flex flex-col gap-1 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="w-14 text-xs tabular-nums text-slate-500">line {row.line}</span>
                  <span className="font-semibold text-slate-100" dir="auto">
                    {row.name}
                  </span>
                  <Chip tone={TONE[row.status as keyof typeof TONE] ?? "default"}>{row.status}</Chip>
                  {row.event ? <span className="text-xs text-slate-500">{row.event}</span> : null}
                </div>
                {row.score ? <p className="ml-16 text-xs text-slate-300" dir="auto">{row.score}</p> : null}
                {[...row.problems, ...row.warnings].length > 0 ? (
                  <ul className="ml-16 list-disc pl-4 text-xs">
                    {row.problems.map((p) => (
                      <li key={p} className="text-red-300">{p}</li>
                    ))}
                    {row.warnings.map((w) => (
                      <li key={w} className="text-amber-300">{w}</li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ul>
          {!result.saved ? (
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Button variant="primary" disabled={busy || ready === 0} onClick={runImport}>
                Import {ready} {ready === 1 ? "match" : "matches"}
              </Button>
              <span className="text-xs text-slate-500">
                Rejected and duplicate rows are skipped.
              </span>
            </div>
          ) : (
            <p className="mt-3 text-xs text-slate-500">
              The imported matches count toward the table tennis rating at once.{" "}
              <Link href="/oversight" className="text-sky-300">Back to oversight</Link>
            </p>
          )}
        </Card>
      ) : null}
    </div>
  );
}
