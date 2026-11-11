"use client";

/**
 * The assistant: a question in plain words, English or Arabic.
 *
 * A local model reads the question into a fixed form; the API then runs that form through the
 * same services as the other screens, as the person asking, and builds the answer from their
 * results (apps/api/app/services/assistant.py). So every number here is the platform's, never
 * the model's. What the model can get wrong is the reading, which is why "How this was read"
 * is printed above every answer, and why every answer links to the screen that shows the same
 * thing with filters a person can set by hand.
 *
 * Answers are drawn as cards and bars (the API's `blocks`), with the plain table one click
 * away, and each ends with questions to ask next about the players in it.
 */

import Link from "next/link";
import { useState } from "react";
import { Avatar, Button, Card, Chip, inputClass } from "@/components/ui";
import { askAssistant } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cx, ordinal } from "@/lib/format";
import { ROLE_IDENTITY } from "@/lib/roles";
import type { AssistantAnswer, AssistantBlock } from "@/lib/types";

const EXAMPLES = [
  "Who broke out this season?",
  "Show me the late bloomers",
  "Best passers among midfielders under 17",
  "Which girls win the most points in table tennis?",
  "مين أحسن هداف تحت ١٦ سنة",
];

type Entry = { id: number; question: string; answer?: AssistantAnswer; error?: string };

export default function AskPage() {
  const { user } = useAuth();
  const accent = ROLE_IDENTITY[user?.role ?? "scout"];
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [entries, setEntries] = useState<Entry[]>([]);

  const ask = async (text: string) => {
    const q = text.trim();
    if (q.length < 2 || busy) return;
    const id = Date.now();
    setBusy(true);
    setQuestion("");
    setEntries((list) => [{ id, question: q }, ...list]);
    const settle = (patch: Partial<Entry>) =>
      setEntries((list) => list.map((e) => (e.id === id ? { ...e, ...patch } : e)));
    try {
      settle({ answer: await askAssistant(q) });
    } catch (err) {
      settle({ error: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className={cx("text-3xl font-bold tracking-tight", accent.text)}>Ask NorthStar</h1>
        <p className="mt-1 text-slate-400">
          Ask about players in plain words, in English or Arabic. Every answer comes from the platform&apos;s own
          records, and only from players you may open.
        </p>
      </div>

      <Card className={cx("border-l-4", accent.border)}>
        <form
          className="flex flex-col gap-3 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            void ask(question);
          }}
        >
          <input
            className={cx(inputClass, "py-3 text-base")}
            dir="auto"
            value={question}
            maxLength={300}
            placeholder="Who broke out this season? How is a player doing? Who plays like them?"
            aria-label="Your question"
            onChange={(e) => setQuestion(e.target.value)}
          />
          <Button type="submit" variant="primary" disabled={busy || question.trim().length < 2}>
            {busy ? "Thinking..." : "Ask"}
          </Button>
        </form>
        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map((example) => (
            <Suggestion key={example} text={example} disabled={busy} onAsk={ask} />
          ))}
        </div>
      </Card>

      {entries.map((entry) => (
        <Card key={entry.id}>
          <p className="mb-3 text-lg font-semibold text-slate-100" dir="auto">
            {entry.question}
          </p>
          {entry.error ? (
            <p className="text-sm text-amber-300">{entry.error}</p>
          ) : !entry.answer ? (
            <Thinking />
          ) : (
            <Answer answer={entry.answer} busy={busy} onAsk={ask} />
          )}
        </Card>
      ))}
    </div>
  );
}

function Suggestion({ text, disabled, onAsk }: { text: string; disabled: boolean; onAsk: (q: string) => void }) {
  return (
    <button
      type="button"
      dir="auto"
      onClick={() => onAsk(text)}
      disabled={disabled}
      className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:border-sky-500 hover:text-sky-200 disabled:opacity-50"
    >
      {text}
    </button>
  );
}

/** What is actually happening while the answer is on its way: the model reads, then the
 * platform looks the reading up. One line for both, because the screen cannot tell which step
 * the API is on. */
function Thinking() {
  return (
    <div className="flex items-center gap-3 text-sm text-slate-400" role="status">
      <span className="flex gap-1" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="h-2 w-2 animate-pulse rounded-full bg-sky-400"
            style={{ animationDelay: `${i * 0.2}s` }}
          />
        ))}
      </span>
      Reading the question, then looking it up in the records
    </div>
  );
}

function Answer({ answer, busy, onAsk }: { answer: AssistantAnswer; busy: boolean; onAsk: (q: string) => void }) {
  const [table, setTable] = useState(false);
  const hasBlocks = answer.blocks.length > 0;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs text-slate-500">How this was read:</span>
        {answer.chips.map((chip) => (
          <Chip key={chip}>{chip}</Chip>
        ))}
      </div>
      <p className="text-slate-200">{answer.answer}</p>

      {hasBlocks && !table ? (
        <div className="flex flex-col gap-4">
          {answer.blocks.map((block, i) => (
            <Block key={i} block={block} />
          ))}
        </div>
      ) : (
        <AnswerTable answer={answer} />
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        {answer.link ? (
          <Link href={answer.link.href} className="text-sky-300 hover:underline">
            {answer.link.label}
          </Link>
        ) : null}
        {hasBlocks && answer.rows.length > 0 ? (
          <button type="button" onClick={() => setTable((t) => !t)} className="text-slate-400 hover:text-slate-200">
            {table ? "Show as cards" : "Show as a table"}
          </button>
        ) : null}
      </div>
      {answer.note ? <p className="text-xs text-slate-500">{answer.note}</p> : null}

      {answer.followUps.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 border-t border-slate-800 pt-3">
          <span className="text-xs text-slate-500">Ask next:</span>
          {answer.followUps.map((q) => (
            <Suggestion key={q} text={q} disabled={busy} onAsk={onAsk} />
          ))}
        </div>
      ) : null}

      {answer.reader === "rules" ? (
        <p className="text-xs text-slate-500">
          Question read by fixed rules, because the local model is not running or is switched off on this
          machine. The rules read fewer
          phrasings than the model; if the reading above is wrong, rephrase or use the link to set the
          filters by hand. The answer and every number in it come from the platform&apos;s own records.
        </p>
      ) : (
        <p className="text-xs text-slate-600">
          Question read by a local model ({answer.model}). The answer and every number in it come from the
          platform&apos;s own records, not from the model.
        </p>
      )}
    </div>
  );
}

function Block({ block }: { block: AssistantBlock }) {
  switch (block.type) {
    case "bars":
      return <Bars block={block} />;
    case "people":
      return <People block={block} />;
    case "verdict":
      return <Verdict block={block} />;
    case "compare":
      return <Compare block={block} />;
  }
}

/** Above the 70th percentile reads as a strength and below the 30th as a weakness, the same
 * lines the scouting report draws. */
function tone(percentile: number | null) {
  if (percentile === null) return "bg-slate-600";
  if (percentile >= 70) return "bg-emerald-400";
  if (percentile <= 30) return "bg-amber-400";
  return "bg-sky-400";
}

function PercentileTrack({ percentile }: { percentile: number | null }) {
  return (
    <div className="relative h-2.5 w-full rounded-full bg-slate-800">
      {percentile !== null ? (
        <div
          className={cx("h-full rounded-full", tone(percentile))}
          style={{ width: `${Math.max(2, percentile)}%` }}
        />
      ) : null}
      {/* The middle of the group, so a bar reads as above or below it at a glance. */}
      <div className="absolute inset-y-[-3px] left-1/2 w-px bg-slate-500" aria-hidden />
    </div>
  );
}

function Name({ id, children }: { id: string | null; children: React.ReactNode }) {
  return id ? (
    <Link href={`/players/${id}`} className="font-semibold text-slate-100 hover:underline">
      <bdi>{children}</bdi>
    </Link>
  ) : (
    <span className="text-slate-200">{children}</span>
  );
}

function Bars({ block }: { block: Extract<AssistantBlock, { type: "bars" }> }) {
  return (
    <div>
      <p className="mb-2 text-xs text-slate-500">{block.title}</p>
      <ul className="flex flex-col gap-2.5">
        {block.items.map((item, i) => (
          <li
            key={`${item.label}-${i}`}
            className="grid grid-cols-[minmax(0,11rem)_minmax(0,1fr)_auto] items-center gap-3 text-sm max-sm:grid-cols-[minmax(0,1fr)_auto]"
          >
            <div className="min-w-0">
              <div className="truncate">
                <Name id={item.playerId}>{item.label}</Name>
              </div>
              {item.sub ? <div className="truncate text-xs text-slate-500">{item.sub}</div> : null}
            </div>
            <div className="max-sm:order-last max-sm:col-span-2">
              <PercentileTrack percentile={item.percentile} />
            </div>
            <div className="text-right tabular-nums">
              <div className="text-slate-200">{item.display}</div>
              {item.percentile !== null ? (
                <div className="text-xs text-slate-500">{ordinal(item.percentile)} percentile</div>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function People({ block }: { block: Extract<AssistantBlock, { type: "people" }> }) {
  return (
    <div className={cx("grid gap-3", block.items.length > 1 && "sm:grid-cols-2")}>
      {block.items.map((p) => (
        <div key={p.playerId} className="flex gap-3 rounded-lg border border-slate-800 bg-slate-900/50 p-3">
          <Avatar size={44} name={p.name} />
          <div className="min-w-0 flex-1">
            <div className="truncate">
              <Name id={p.playerId}>{p.name}</Name>
            </div>
            {p.sub ? <p className="truncate text-xs text-slate-500">{p.sub}</p> : null}
            {p.tags.length > 0 ? (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {p.tags.map((t) => (
                  <Chip key={t} tone={t === "late bloomer" || t === "breakout" ? "brand" : t === "confirmed" ? "good" : "default"}>
                    {t}
                  </Chip>
                ))}
              </div>
            ) : null}
            {p.text ? <p className="mt-1.5 text-sm text-slate-300">{p.text}</p> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

const GRADE_COLOUR: Record<string, string> = {
  A: "text-emerald-300",
  B: "text-emerald-400",
  C: "text-slate-200",
  D: "text-amber-400",
};

function Verdict({ block }: { block: Extract<AssistantBlock, { type: "verdict" }> }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Current level</p>
          <p className={cx("text-4xl font-bold leading-none", GRADE_COLOUR[block.grade ?? ""] ?? "text-slate-300")}>
            {block.grade ?? "n/a"}
          </p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Recommendation</p>
          <p className="text-xl font-bold">{block.recommendation ?? "None"}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Confidence</p>
          <p className="font-semibold capitalize">{block.confidence}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {block.areas.map((a) => (
            <div key={a.label} className="rounded-md border border-slate-800 px-2.5 py-1 text-center">
              <p className={cx("text-lg font-bold leading-none", GRADE_COLOUR[a.grade ?? ""] ?? "text-slate-400")}>
                {a.grade ?? "n/a"}
              </p>
              <p className="mt-0.5 text-[0.7rem] text-slate-400">{a.label}</p>
            </div>
          ))}
        </div>
      </div>
      <p className="mt-3 text-sm text-slate-200">{block.summary}</p>
      <p className="mt-1 text-xs text-slate-500">
        Scouting report: {block.context}.{" "}
        <Link href={`/players/${block.playerId}/report`} className="text-sky-300 hover:underline">
          Read it
        </Link>
      </p>
    </div>
  );
}

function Compare({ block }: { block: Extract<AssistantBlock, { type: "compare" }> }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[28rem] border-collapse text-sm">
        <thead>
          <tr>
            <th className="w-36 border-b border-slate-700 px-2 py-2 text-left text-xs font-medium text-slate-500" />
            {block.players.map((p) => (
              <th key={p.playerId} className="border-b border-slate-700 px-2 py-2 text-left font-semibold">
                <Name id={p.playerId}>{p.name}</Name>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row) => {
            const best = Math.max(...row.cells.map((c) => c.percentile ?? -1));
            return (
              <tr key={row.label}>
                <td className="border-b border-slate-800/70 px-2 py-2 text-slate-400">{row.label}</td>
                {row.cells.map((c, i) => (
                  <td key={i} className="border-b border-slate-800/70 px-2 py-2">
                    <div className="flex items-baseline justify-between gap-2 tabular-nums">
                      <span className={cx(c.percentile !== null && c.percentile === best && best >= 0 ? "font-semibold text-slate-100" : "text-slate-300")}>
                        {c.display}
                      </span>
                      <span className="text-xs text-slate-500">{c.percentile !== null ? ordinal(c.percentile) : "no rank"}</span>
                    </div>
                    <div className="mt-1">
                      <PercentileTrack percentile={c.percentile} />
                    </div>
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-slate-500">The longest bar in each row is in bold. The line marks the middle of the group.</p>
    </div>
  );
}

function AnswerTable({ answer }: { answer: AssistantAnswer }) {
  if (answer.rows.length === 0) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            {answer.columns.map((column, i) => (
              <th
                key={column}
                className={cx(
                  "border-b border-slate-700 px-2 py-2 text-xs font-medium text-slate-500",
                  i === 0 ? "text-left" : "text-right",
                )}
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {answer.rows.map((row, r) => (
            <tr key={r}>
              {row.cells.map((cell, i) => (
                <td
                  key={i}
                  dir={i === 0 ? "auto" : undefined}
                  className={cx(
                    "border-b border-slate-800/70 px-2 py-2 text-slate-300",
                    i === 0 ? "text-left" : "text-right tabular-nums",
                  )}
                >
                  {i === 0 && row.playerId ? (
                    <Link href={`/players/${row.playerId}`} className="text-sky-300 hover:underline">
                      <bdi>{cell}</bdi>
                    </Link>
                  ) : (
                    cell
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
