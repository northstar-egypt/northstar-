"use client";

/**
 * Integrity board. See docs/wireframes/08-integrity-board.html.
 *
 * A work queue, not a dashboard. Every fraud, duplicate, and anomaly flag arrives here and a
 * human decides.
 *
 * This screen has a second job that is easy to miss: each decision plus its reason is a
 * labelled example, and labelled examples are what the detectors' precision and recall are
 * computed from. That is why the reason field is required, and why there are three outcomes
 * rather than two. Without "needs more information", cases that cannot be decided today get
 * dismissed to clear the queue, which quietly poisons the data the ML track is graded on.
 *
 * BLOCKED: there is no flag table in docs/schema.md. See lib/api.ts.
 */

import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Chip,
  Empty,
  Label,
  SectionTitle,
  Skeleton,
  Table,
  Td,
  Th,
  inputClass,
} from "@/components/ui";
import { decideFlag, getFlags } from "@/lib/api";
import { cx } from "@/lib/format";
import type { IntegrityFlag } from "@/lib/types";

type Decision = "confirmed" | "dismissed" | "needs_info";

const TONE: Record<IntegrityFlag["type"], "bad" | "warn" | "brand"> = {
  fraud: "bad",
  duplicate: "brand",
  anomaly: "warn",
};

export default function IntegrityPage() {
  const [flags, setFlags] = useState<IntegrityFlag[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState<Decision | null>(null);
  const [resolved, setResolved] = useState<Record<string, Decision>>({});

  useEffect(() => {
    let alive = true;
    getFlags().then((f) => {
      if (!alive) return;
      setFlags(f);
      setSelectedId(f[0]?.id ?? null);
    });
    return () => {
      alive = false;
    };
  }, []);

  const open = useMemo(
    () => (flags ?? []).filter((f) => !resolved[f.id]),
    [flags, resolved],
  );
  const selected = useMemo(
    () => (flags ?? []).find((f) => f.id === selectedId) ?? null,
    [flags, selectedId],
  );

  const counts = useMemo(() => {
    const c = { fraud: 0, duplicate: 0, anomaly: 0 };
    open.forEach((f) => {
      c[f.type] += 1;
    });
    return c;
  }, [open]);

  async function decide(decision: Decision) {
    if (!selected || reason.trim().length < 3) return;
    setPending(decision);
    await decideFlag(selected.id, decision, reason.trim());
    setResolved((r) => ({ ...r, [selected.id]: decision }));
    setReason("");
    setPending(null);
    const next = open.find((f) => f.id !== selected.id);
    setSelectedId(next?.id ?? null);
  }

  if (!flags) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-16" />
        <Skeleton className="h-96" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">
            {open.length} open {open.length === 1 ? "flag" : "flags"}
          </h1>
          <p className="text-sm text-slate-500">
            {open.length > 0
              ? `oldest has been waiting ${Math.max(...open.map((f) => f.ageDays))} days`
              : "queue is clear"}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Chip tone="bad">fraud {counts.fraud}</Chip>
          <Chip tone="brand">duplicate {counts.duplicate}</Chip>
          <Chip tone="warn">anomaly {counts.anomaly}</Chip>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[15rem_1fr]">
        {/* queue */}
        <div className="flex flex-col gap-2">
          {open.length === 0 ? (
            <Empty>Queue is clear.</Empty>
          ) : (
            open.map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => {
                  setSelectedId(f.id);
                  setReason("");
                }}
                className={cx(
                  "rounded-lg border p-3 text-left transition",
                  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400",
                  f.id === selectedId
                    ? "border-sky-600 bg-slate-900"
                    : "border-slate-800 bg-slate-900/40 hover:border-slate-600",
                )}
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <Chip tone={TONE[f.type]}>{f.type}</Chip>
                  <span className="text-xs tabular-nums text-slate-500">{f.ageDays}d</span>
                </div>
                <p className="text-sm font-semibold text-slate-100">{f.playerName}</p>
                <p className="text-xs text-slate-500">{f.organizationName ?? "self submitted"}</p>
              </button>
            ))
          )}
        </div>

        {/* detail */}
        {!selected || resolved[selected.id] ? (
          <Empty>Select a flag from the queue.</Empty>
        ) : (
          <div className="flex flex-col gap-4">
            <Card>
              <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h2 className="text-lg font-bold tracking-tight">
                    {selected.type === "duplicate"
                      ? "Possible duplicate record"
                      : selected.type === "fraud"
                        ? "Possible self submission fraud"
                        : "Measurement anomaly"}
                  </h2>
                  <p className="text-xs text-slate-500">
                    {selected.playerName} &middot; raised {selected.ageDays} days ago
                  </p>
                </div>
                <Chip
                  tone={TONE[selected.type]}
                  title="The model's own number. Converting it to a word would lose the feedback the ML track needs."
                >
                  confidence {selected.confidence.toFixed(2)}
                </Chip>
              </div>

              {/* Evidence before verdict. A reviewer must be able to disagree with the model,
                  which means seeing what it matched on rather than a score alone. */}
              <div className="rounded-md border border-slate-800 bg-slate-900/60 p-3">
                <Label>Why this was raised</Label>
                <p className="mt-1 text-sm text-slate-300">{selected.reason}</p>
                <ul className="mt-2 flex list-disc flex-col gap-0.5 pl-4 text-xs text-slate-400">
                  {selected.evidence.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              </div>

              {selected.records ? (
                <div className="mt-3">
                  <SectionTitle>Field by field</SectionTitle>
                  <Table>
                    <thead>
                      <tr>
                        <Th>Field</Th>
                        <Th>Record A</Th>
                        <Th>Record B</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {selected.records.fields.map((f) => (
                        <tr key={f.field} className={f.differs ? "bg-amber-950/20" : undefined}>
                          <Td className="text-slate-500">{f.field}</Td>
                          <Td className={f.differs ? "text-amber-200" : undefined}>{f.a}</Td>
                          <Td className={f.differs ? "text-amber-200" : undefined}>{f.b}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                  <p className="mt-2 text-xs text-slate-500">
                    Record A has more history, so it is the one that should survive a merge. The
                    schema supports this directly through merged_into.
                  </p>
                </div>
              ) : null}
            </Card>

            <Card>
              <SectionTitle>Decision</SectionTitle>
              <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                  <Label>Reason, recorded with the decision</Label>
                  <input
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Rang the academy, confirmed they are two different boys."
                    className={inputClass}
                  />
                  <span className="text-xs text-slate-500">
                    Required. A decision without a reason is a lost training signal.
                  </span>
                </div>

                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="ghost"
                    disabled={reason.trim().length < 3 || pending !== null}
                    onClick={() => decide("dismissed")}
                  >
                    {pending === "dismissed" ? "Saving" : "Not a real flag"}
                  </Button>
                  <Button
                    disabled={reason.trim().length < 3 || pending !== null}
                    onClick={() => decide("needs_info")}
                  >
                    {pending === "needs_info" ? "Saving" : "Needs more information"}
                  </Button>
                  <Button
                    variant="primary"
                    disabled={reason.trim().length < 3 || pending !== null}
                    onClick={() => decide("confirmed")}
                  >
                    {pending === "confirmed"
                      ? "Saving"
                      : selected.type === "duplicate"
                        ? "Confirm and merge"
                        : "Confirm"}
                  </Button>
                </div>
              </div>
            </Card>

            <Card className="bg-slate-900/40">
              <SectionTitle>History</SectionTitle>
              <Table>
                <thead>
                  <tr>
                    <Th>When</Th>
                    <Th>Who</Th>
                    <Th>What</Th>
                  </tr>
                </thead>
                <tbody>
                  {selected.history.map((h, i) => (
                    <tr key={i}>
                      <Td className="whitespace-nowrap text-slate-500">{h.at}</Td>
                      <Td>{h.who}</Td>
                      <Td>{h.what}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <p className="mt-2 text-xs text-slate-500">
                Visible so two reviewers do not work the same flag, and so a decision can be
                revisited later with its context intact.
              </p>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}
