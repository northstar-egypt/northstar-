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
 */

import Link from "next/link";
import { useState } from "react";
import { Button, Card, Chip, inputClass } from "@/components/ui";
import { askAssistant } from "@/lib/api";
import type { AssistantAnswer } from "@/lib/types";

const EXAMPLES = [
  "Best passers among midfielders under 17",
  "Which girls win the most points in table tennis?",
  "مين أحسن هداف تحت ١٦ سنة",
  "Most hardworking defenders aged 14 to 16",
];

type Entry = { question: string; answer?: AssistantAnswer; error?: string };

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [entries, setEntries] = useState<Entry[]>([]);

  const ask = async (text: string) => {
    const q = text.trim();
    if (q.length < 2 || busy) return;
    setBusy(true);
    setQuestion("");
    setEntries((list) => [{ question: q }, ...list]);
    try {
      const answer = await askAssistant(q);
      setEntries((list) => [{ question: q, answer }, ...list.slice(1)]);
    } catch (err) {
      setEntries((list) => [{ question: q, error: (err as Error).message }, ...list.slice(1)]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Ask</h1>
        <p className="text-sm text-slate-400">
          Ask about players in plain words, in English or Arabic. The answer comes from the match
          records, and only from players you may open.
        </p>
      </div>

      <Card>
        <form
          className="flex flex-col gap-3 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            void ask(question);
          }}
        >
          <input
            className={inputClass}
            dir="auto"
            value={question}
            maxLength={300}
            placeholder="Who are the best passers among midfielders under 17?"
            aria-label="Your question"
            onChange={(e) => setQuestion(e.target.value)}
          />
          <Button type="submit" variant="primary" disabled={busy || question.trim().length < 2}>
            {busy ? "Reading..." : "Ask"}
          </Button>
        </form>
        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              dir="auto"
              onClick={() => void ask(example)}
              disabled={busy}
              className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:border-sky-500 hover:text-sky-200 disabled:opacity-50"
            >
              {example}
            </button>
          ))}
        </div>
      </Card>

      {entries.map((entry, i) => (
        <Card key={`${entries.length - i}`}>
          <p className="mb-3 text-sm font-semibold text-slate-100" dir="auto">
            {entry.question}
          </p>
          {entry.error ? (
            <p className="text-sm text-amber-300">{entry.error}</p>
          ) : !entry.answer ? (
            <p className="text-sm text-slate-500">Reading the question...</p>
          ) : (
            <Answer answer={entry.answer} />
          )}
        </Card>
      ))}
    </div>
  );
}

function Answer({ answer }: { answer: AssistantAnswer }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs text-slate-500">How this was read:</span>
        {answer.chips.map((chip) => (
          <Chip key={chip}>{chip}</Chip>
        ))}
      </div>
      <p className="text-sm text-slate-200">{answer.answer}</p>
      {answer.rows.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                {answer.columns.map((column, i) => (
                  <th
                    key={column}
                    className={
                      "border-b border-slate-700 px-2 py-2 text-[0.66rem] font-medium uppercase tracking-[0.1em] text-slate-500 " +
                      (i === 0 ? "text-left" : "text-right")
                    }
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
                      className={
                        "border-b border-slate-800/70 px-2 py-2 text-slate-300 " +
                        (i === 0 ? "text-left" : "text-right tabular-nums")
                      }
                    >
                      {i === 0 && row.playerId ? (
                        <Link href={`/players/${row.playerId}`} className="text-sky-300 hover:underline">
                          {cell}
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
      ) : null}
      {answer.link ? (
        <Link href={answer.link.href} className="text-sm text-sky-300 hover:underline">
          {answer.link.label}
        </Link>
      ) : null}
      {answer.note ? <p className="text-xs text-slate-500">{answer.note}</p> : null}
      <p className="text-xs text-slate-600">
        Question read by a local model ({answer.model}). The answer and every number in it come
        from the platform&apos;s own records, not from the model.
      </p>
    </div>
  );
}
