"use client";

/**
 * Import players from a spreadsheet. See apps/api/app/services/imports.py.
 *
 * Three steps, and the first two save nothing: choose a CSV, read every row's verdict, then
 * import the ready rows and the ones the coach confirms. The file is read in the browser and
 * sent as text; it is never uploaded as a file or stored. Every row goes through the same
 * checks as a player added by hand, consent form included.
 */

import Link from "next/link";
import { useMemo, useState } from "react";
import { Banner, Button, Card, Chip, SectionTitle } from "@/components/ui";
import { importPlayers, previewImport } from "@/lib/api";
import type { PlayerImport } from "@/lib/types";

const TEMPLATE_COLUMNS: [string, string][] = [
  ["full_name", "Full name (required)"],
  ["known_as", "Name used day to day"],
  ["date_of_birth", "YYYY-MM-DD (required)"],
  ["gender", "male or female"],
  ["sport", "football or table_tennis (required)"],
  ["position", "e.g. ST, CB"],
  ["tier", "football: pro, youth or diaspora"],
  ["nationality", "two-letter codes, several separated by ; (EG;FR)"],
  ["egypt_eligible", "yes or no"],
  ["consent_signed", "yes: the sign-up consent form is signed (required)"],
  ["guardian_name", "required for a player under 18"],
  ["measured_on", "YYYY-MM-DD, the date of the readings"],
  ["height_cm", "cm"],
  ["weight_kg", "kg"],
  ["sprint_10m_s", "seconds"],
  ["confidence", "measured or estimated"],
];

const TONE = {
  ready: "good",
  created: "good",
  confirm: "warn",
  skipped: "warn",
  rejected: "bad",
} as const;

function downloadTemplate() {
  // Column names only, built here, so there is no template file that could ever hold a row
  // of real data.
  const blob = new Blob([TEMPLATE_COLUMNS.map(([name]) => name).join(",") + "\n"], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "northstar-players-template.csv";
  link.click();
  URL.revokeObjectURL(url);
}

export default function ImportPlayersPage() {
  const [text, setText] = useState<string | null>(null);
  const [fileName, setFileName] = useState("");
  const [result, setResult] = useState<PlayerImport | null>(null);
  const [confirmed, setConfirmed] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function choose(file: File | undefined) {
    setResult(null);
    setConfirmed(new Set());
    setError(null);
    if (!file) return;
    setFileName(file.name);
    const content = await file.text();
    setText(content);
    setBusy(true);
    try {
      setResult(await previewImport(content));
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
      setResult(await importPlayers(text, [...confirmed]));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const toImport = useMemo(() => {
    if (!result || result.saved) return 0;
    return result.rows.filter(
      (r) => r.status === "ready" || (r.status === "confirm" && confirmed.has(r.line)),
    ).length;
  }, [result, confirmed]);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Import players</h1>
        <p className="text-sm text-slate-500">
          From a spreadsheet saved as CSV. Nothing is saved until you press Import.
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
          Every player needs a signed consent form, and a player under 18 a named guardian, as
          when adding a player by hand. The file stays on this device until you import; only the
          players it creates are saved.
        </p>
      </Card>

      {error ? <Banner tone="bad" title="Not done">{error}</Banner> : null}
      {busy ? <p className="text-sm text-slate-400">Checking every row...</p> : null}

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
          <SectionTitle>
            {result.saved ? "3. Imported" : `2. Check every row of ${fileName}`}
          </SectionTitle>
          <div className="mb-3 flex flex-wrap gap-2">
            {Object.entries(result.counts).map(([status, n]) => (
              <Chip key={status} tone={TONE[status as keyof typeof TONE] ?? "default"}>
                {n} {status}
              </Chip>
            ))}
          </div>
          <ul className="flex flex-col divide-y divide-slate-800">
            {result.rows.map((row) => (
              <li key={row.line} className="flex flex-col gap-1 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="w-14 text-xs tabular-nums text-slate-500">line {row.line}</span>
                  {row.playerId ? (
                    <Link href={`/players/${row.playerId}`} className="font-semibold text-slate-100 hover:text-sky-300">
                      {row.name || "(no name)"}
                    </Link>
                  ) : (
                    <span className="font-semibold text-slate-100">{row.name || "(no name)"}</span>
                  )}
                  <Chip tone={TONE[row.status]}>{row.status}</Chip>
                  {!result.saved && row.status === "confirm" ? (
                    <label className="flex items-center gap-1 text-xs text-amber-300">
                      <input
                        type="checkbox"
                        checked={confirmed.has(row.line)}
                        onChange={(e) => {
                          const next = new Set(confirmed);
                          if (e.target.checked) next.add(row.line);
                          else next.delete(row.line);
                          setConfirmed(next);
                        }}
                      />
                      I checked this, import it
                    </label>
                  ) : null}
                </div>
                {[...row.problems, ...row.warnings].length > 0 ? (
                  <ul className="ml-16 list-disc pl-4 text-xs text-slate-400">
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
              <Button variant="primary" disabled={busy || toImport === 0} onClick={runImport}>
                Import {toImport} {toImport === 1 ? "player" : "players"}
              </Button>
              <span className="text-xs text-slate-500">
                Rejected rows are skipped. Fix them in the spreadsheet and import that file again.
              </span>
            </div>
          ) : (
            <p className="mt-3 text-xs text-slate-500">
              Rows that were not imported are listed above with the reason. <Link href="/dashboard" className="text-sky-300">Back to the squad</Link>
            </p>
          )}
        </Card>
      ) : null}
    </div>
  );
}
