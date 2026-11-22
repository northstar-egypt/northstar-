"use client";

/**
 * Players abroad: diaspora submissions (decision 0011; apps/api/app/services/submissions.py).
 *
 * Scouts, federation staff and players submit an Egypt-eligible player abroad, with a source
 * where the claims can be checked. Nothing becomes a player record until federation staff
 * approve it, and the checks on arrival are shown to the reviewer with their evidence: the
 * same person on record, a different date of birth under the same name, numbers above
 * everyone in the league, and the submitter's record. Submitted seasons stay marked as
 * submitted and are never counted in league comparisons.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Banner, Button, Card, Chip, Empty, Field, SectionTitle, Skeleton, Table, Td, Th, inputClass } from "@/components/ui";
import {
  ApiError,
  createSubmission,
  decideSubmission,
  getMySubmissions,
  getSubmissionQueue,
  recordSubmissionConsent,
  updateSubmission,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Submission, SubmissionCheck, SubmissionInput, SubmittedSeason } from "@/lib/types";

const BASES: { value: string; label: string }[] = [
  { value: "egyptian_nationality", label: "Holds Egyptian nationality" },
  { value: "born_in_egypt", label: "Born in Egypt" },
  { value: "parent_born_in_egypt", label: "A parent born in Egypt" },
  { value: "grandparent_born_in_egypt", label: "A grandparent born in Egypt" },
  { value: "other", label: "Other (say what in the note)" },
];

const STATUS: Record<Submission["status"], { label: string; tone: "default" | "good" | "warn" | "bad" | "brand" }> = {
  pending: { label: "Waiting for review", tone: "brand" },
  awaiting_consent: { label: "Waiting for consent", tone: "warn" },
  needs_info: { label: "More information asked", tone: "warn" },
  approved: { label: "Approved", tone: "good" },
  rejected: { label: "Rejected", tone: "bad" },
};

const COUNTS: { key: string; label: string }[] = [
  { key: "appearances", label: "Apps" },
  { key: "minutes_played", label: "Minutes" },
  { key: "goals", label: "Goals" },
  { key: "assists", label: "Assists" },
  { key: "penalty_goals", label: "Pen goals" },
  { key: "yellow_cards", label: "Yellow" },
  { key: "red_cards", label: "Red" },
];

function problemsOf(error: unknown): string[] {
  if (error instanceof ApiError) {
    const detail = error.detail as { problems?: string[] } | null;
    if (detail?.problems?.length) return detail.problems;
    return [error.message];
  }
  return [(error as Error).message];
}

function isWebAddress(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

function SourceLink({ url }: { url: string }) {
  // The API refuses anything but http(s); this is a second guard against a script address.
  if (!isWebAddress(url)) return <span>{url}</span>;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer nofollow" className="break-all text-sky-300 hover:underline">
      {url}
    </a>
  );
}

export default function SubmissionsPage() {
  const { user } = useAuth();
  const reviewer = user?.role === "federation";
  const [tab, setTab] = useState<"queue" | "submit" | "mine">(reviewer ? "queue" : "submit");
  const [editing, setEditing] = useState<Submission | null>(null);

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Players abroad</h1>
        <p className="text-sm text-slate-400">
          Submit an Egypt-eligible player playing abroad. The federation checks every submission before the player is
          added.
        </p>
      </div>
      <div className="flex flex-wrap gap-2" role="tablist">
        {reviewer ? (
          <Button variant={tab === "queue" ? "primary" : "default"} onClick={() => setTab("queue")} role="tab" aria-selected={tab === "queue"}>
            To review
          </Button>
        ) : null}
        <Button
          variant={tab === "submit" ? "primary" : "default"}
          onClick={() => {
            setEditing(null);
            setTab("submit");
          }}
          role="tab"
          aria-selected={tab === "submit"}
        >
          {editing ? "Edit submission" : "Submit a player"}
        </Button>
        <Button variant={tab === "mine" ? "primary" : "default"} onClick={() => setTab("mine")} role="tab" aria-selected={tab === "mine"}>
          My submissions
        </Button>
      </div>
      {tab === "queue" ? <Queue /> : null}
      {tab === "submit" ? (
        <SubmitForm
          key={editing?.id ?? "new"}
          editing={editing}
          isPlayer={user?.role === "player"}
          onSaved={() => {
            setEditing(null);
            setTab("mine");
          }}
        />
      ) : null}
      {tab === "mine" ? (
        <Mine
          onEdit={(s) => {
            setEditing(s);
            setTab("submit");
          }}
        />
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------------- the form */

type SeasonRow = { competition: string; season: string; group: string } & Record<string, string>;

function toRow(s: SubmittedSeason): SeasonRow {
  const row: SeasonRow = { competition: s.competition, season: s.season, group: String(s.metrics.position_group ?? "") };
  for (const c of COUNTS) row[c.key] = s.metrics[c.key] == null ? "" : String(s.metrics[c.key]);
  return row;
}

function fromRow(row: SeasonRow): SubmittedSeason {
  const metrics: Record<string, number | string> = {};
  if (row.group) metrics.position_group = row.group;
  for (const c of COUNTS) if (row[c.key] !== "") metrics[c.key] = Number(row[c.key]);
  return { competition: row.competition.trim(), season: row.season.trim(), metrics };
}

const EMPTY_ROW: SeasonRow = {
  competition: "",
  season: "",
  group: "",
  ...Object.fromEntries(COUNTS.map((c) => [c.key, ""])),
} as SeasonRow;

function ageOn(dob: string): number | null {
  if (!dob) return null;
  const born = new Date(dob);
  const now = new Date();
  let age = now.getFullYear() - born.getFullYear();
  if (now < new Date(now.getFullYear(), born.getMonth(), born.getDate())) age -= 1;
  return age;
}

function SubmitForm({
  editing,
  isPlayer,
  onSaved,
}: {
  editing: Submission | null;
  isPlayer: boolean;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    fullName: editing?.fullName ?? "",
    knownAs: editing?.knownAs ?? "",
    dateOfBirth: editing?.dateOfBirth ?? "",
    sex: editing?.sex ?? "male",
    nationality: (editing?.nationality ?? ["EG"]).join(", "),
    eligibilityBasis: editing?.eligibilityBasis ?? "egyptian_nationality",
    position: editing?.position ?? "",
    clubName: editing?.clubName ?? "",
    clubCountry: editing?.clubCountry ?? "",
    competition: editing?.competition ?? "",
    sourceUrl: editing?.sourceUrl ?? "",
    note: editing?.note ?? "",
  });
  const [seasons, setSeasons] = useState<SeasonRow[]>((editing?.seasons ?? []).map(toRow));
  const [signed, setSigned] = useState(Boolean(editing?.consent.signed));
  const [guardian, setGuardian] = useState(editing?.consent.guardianName ?? "");
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const age = ageOn(form.dateOfBirth);
  const minor = age != null && age < 18;
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  async function save() {
    setBusy(true);
    setProblems([]);
    const input: SubmissionInput = {
      ...form,
      knownAs: form.knownAs || null,
      position: form.position || null,
      competition: form.competition || null,
      nationality: form.nationality.split(",").map((c) => c.trim().toUpperCase()).filter(Boolean),
      seasons: seasons.map(fromRow),
      consent: signed ? { signed: true, guardianName: minor ? guardian || null : null } : null,
    };
    try {
      if (editing) await updateSubmission(editing.id, input);
      else await createSubmission(input);
      onSaved();
    } catch (e) {
      setProblems(problemsOf(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <SectionTitle>{editing ? `Edit: ${editing.fullName}` : "Submit a player abroad"}</SectionTitle>
      {editing?.reviewReason && editing.status === "needs_info" ? (
        <Banner tone="warn" title="The reviewer asked for more">
          {editing.reviewReason}
        </Banner>
      ) : null}
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Field label="Full name">
          <input className={inputClass} value={form.fullName} onChange={set("fullName")} />
        </Field>
        <Field label="Known as" hint="Optional">
          <input className={inputClass} value={form.knownAs} onChange={set("knownAs")} />
        </Field>
        <Field label="Date of birth">
          <input type="date" className={inputClass} value={form.dateOfBirth} onChange={set("dateOfBirth")} />
        </Field>
        <Field label="Gender">
          <select className={inputClass} value={form.sex} onChange={set("sex")}>
            <option value="male">Male</option>
            <option value="female">Female</option>
          </select>
        </Field>
        <Field label="Nationalities" hint="Two-letter codes, comma separated: EG, DE">
          <input className={inputClass} value={form.nationality} onChange={set("nationality")} />
        </Field>
        <Field label="Why they could play for Egypt">
          <select className={inputClass} value={form.eligibilityBasis} onChange={set("eligibilityBasis")}>
            {BASES.map((b) => (
              <option key={b.value} value={b.value}>
                {b.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Position" hint="Optional: GK, CB, RB, LB, CDM, CM, CAM, LW, RW, ST">
          <input className={inputClass} value={form.position} onChange={set("position")} />
        </Field>
        <Field label="Club abroad">
          <input className={inputClass} value={form.clubName} onChange={set("clubName")} />
        </Field>
        <Field label="Club's country" hint="Two-letter code: DE, FR, US">
          <input className={inputClass} value={form.clubCountry} onChange={set("clubCountry")} maxLength={2} />
        </Field>
        <Field label="League" hint="Optional">
          <input className={inputClass} value={form.competition} onChange={set("competition")} />
        </Field>
        <Field label="Source" hint="A club, league or federation page where the federation can check the claims">
          <input className={inputClass} value={form.sourceUrl} onChange={set("sourceUrl")} placeholder="https://" />
        </Field>
        <Field label="Note" hint="Anything the reviewer should know">
          <textarea className={inputClass} rows={2} value={form.note} onChange={set("note")} />
        </Field>
      </div>

      <div className="mt-5">
        <p className="mb-1 text-sm font-semibold text-slate-200">League seasons (optional)</p>
        <p className="mb-2 text-xs text-slate-500">
          As the source publishes them. They are shown on the profile as submitted and never counted in league
          comparisons.
        </p>
        {seasons.map((row, i) => (
          <div key={i} className="mb-2 grid grid-cols-2 gap-2 sm:grid-cols-5 lg:grid-cols-10">
            <input className={inputClass} placeholder="League" value={row.competition}
              onChange={(e) => setSeasons(seasons.map((r, j) => (j === i ? { ...r, competition: e.target.value } : r)))} />
            <input className={inputClass} placeholder="2024/25" value={row.season}
              onChange={(e) => setSeasons(seasons.map((r, j) => (j === i ? { ...r, season: e.target.value } : r)))} />
            <select className={inputClass} value={row.group} aria-label="Position group"
              onChange={(e) => setSeasons(seasons.map((r, j) => (j === i ? { ...r, group: e.target.value } : r)))}>
              <option value="">Group</option>
              <option value="goalkeeper">Goalkeeper</option>
              <option value="defender">Defender</option>
              <option value="midfielder">Midfielder</option>
              <option value="forward">Forward</option>
            </select>
            {COUNTS.map((c) => (
              <input key={c.key} className={inputClass} inputMode="numeric" placeholder={c.label} aria-label={c.label}
                value={row[c.key]}
                onChange={(e) => setSeasons(seasons.map((r, j) => (j === i ? { ...r, [c.key]: e.target.value } : r)))} />
            ))}
          </div>
        ))}
        <div className="flex gap-2">
          <Button size="sm" disabled={seasons.length >= 10} onClick={() => setSeasons([...seasons, { ...EMPTY_ROW }])}>
            Add a season
          </Button>
          {seasons.length ? (
            <Button size="sm" variant="ghost" onClick={() => setSeasons(seasons.slice(0, -1))}>
              Remove the last
            </Button>
          ) : null}
        </div>
      </div>

      <div className="mt-5 rounded-lg border border-slate-800 p-3">
        <label className="flex items-start gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={signed} onChange={(e) => setSigned(e.target.checked)} className="mt-1" />
          <span>
            {isPlayer
              ? "I have signed the sign-up consent form (storage, analytics and scouting visibility)."
              : "The sign-up consent form has been signed, by the player, or for a minor by a named guardian."}
          </span>
        </label>
        {minor && signed ? (
          <Field label="Guardian who signed">
            <input className={inputClass} value={guardian} onChange={(e) => setGuardian(e.target.value)} />
          </Field>
        ) : null}
        <p className="mt-2 text-xs text-slate-500">
          Without a recorded form the submission waits until the federation records it. A scout cannot record it for a
          minor: the federation contacts the guardian.
        </p>
      </div>

      {problems.length ? (
        <div className="mt-4">
          <Banner tone="bad" title="Not saved">
            <ul className="list-disc pl-5">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </Banner>
        </div>
      ) : null}
      <div className="mt-4">
        <Button variant="primary" disabled={busy} onClick={() => void save()}>
          {busy ? "Saving..." : editing ? "Save and send again" : "Submit"}
        </Button>
      </div>
    </Card>
  );
}

/* ------------------------------------------------------- the submitter's list */

function Mine({ onEdit }: { onEdit: (s: Submission) => void }) {
  const [rows, setRows] = useState<Submission[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMySubmissions()
      .then(setRows)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <Banner tone="warn" title="Could not load">{error}</Banner>;
  if (!rows) return <Skeleton className="h-40" />;
  if (!rows.length) return <Empty>You have not submitted anyone yet.</Empty>;
  return (
    <Card>
      <Table>
        <thead>
          <tr>
            <Th>Player</Th>
            <Th>Club</Th>
            <Th>Status</Th>
            <Th>Reviewer&apos;s reason</Th>
            <Th>{""}</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id}>
              <Td>
                {s.playerId && s.status === "approved" ? (
                  <Link href={`/players/${s.playerId}`} className="text-sky-300 hover:underline">
                    <bdi>{s.fullName}</bdi>
                  </Link>
                ) : (
                  <bdi>{s.fullName}</bdi>
                )}
                <span className="block text-xs text-slate-500">submitted {s.createdAt.slice(0, 10)}</span>
              </Td>
              <Td>
                {s.clubName} ({s.clubCountry})
              </Td>
              <Td>
                <Chip tone={STATUS[s.status].tone}>{STATUS[s.status].label}</Chip>
              </Td>
              <Td className="text-xs text-slate-400">{s.reviewReason ?? ""}</Td>
              <Td>
                {["pending", "needs_info", "awaiting_consent"].includes(s.status) ? (
                  <Button size="sm" onClick={() => onEdit(s)}>
                    Edit
                  </Button>
                ) : null}
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}

/* ----------------------------------------------------------------- the queue */

function daysSince(iso: string): number {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000));
}

function Queue() {
  const [rows, setRows] = useState<Submission[] | null>(null);
  const [open, setOpen] = useState<Submission | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    getSubmissionQueue()
      .then((r) => {
        setRows(r);
        setOpen((now) => (now ? r.find((s) => s.id === now.id) ?? null : null));
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  if (error) return <Banner tone="warn" title="Could not load">{error}</Banner>;
  if (!rows) return <Skeleton className="h-40" />;
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,20rem)_1fr]">
      <Card>
        <SectionTitle>To review, oldest first</SectionTitle>
        {!rows.length ? (
          <Empty>Nothing waiting.</Empty>
        ) : (
          <ul className="flex flex-col gap-1">
            {rows.map((s) => {
              const attention = s.checks.filter((c) => c.outcome === "attention").length;
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => setOpen(s)}
                    className={`w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-800 ${open?.id === s.id ? "bg-slate-800" : ""}`}
                  >
                    <bdi className="font-medium text-slate-100">{s.fullName}</bdi>
                    <span className="block text-xs text-slate-400">
                      {STATUS[s.status].label}, {daysSince(s.createdAt)} day(s) old
                      {attention ? `, ${attention} check(s) to look at` : ""}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
      {open ? <Review submission={open} onDone={load} /> : <Empty>Pick a submission to review.</Empty>}
    </div>
  );
}

const OUTCOME: Record<SubmissionCheck["outcome"], { tone: "good" | "warn" | "default"; label: string }> = {
  clear: { tone: "good", label: "Clear" },
  attention: { tone: "warn", label: "Look at this" },
  not_run: { tone: "default", label: "Not compared" },
  info: { tone: "default", label: "For information" },
};

function Review({ submission: s, onDone }: { submission: Submission; onDone: () => void }) {
  const [action, setAction] = useState<"approve" | "attach" | "reject" | "needs_info">("approve");
  const [reason, setReason] = useState("");
  const [playerId, setPlayerId] = useState("");
  const [guardian, setGuardian] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const candidates = s.checks.flatMap((c) => c.matches).filter((m) => m.kind === "player");

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setProblems([]);
    try {
      await fn();
      setReason("");
      onDone();
    } catch (e) {
      setProblems(problemsOf(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <SectionTitle>
        <bdi>{s.fullName}</bdi>
        {s.knownAs ? ` (${s.knownAs})` : ""}
      </SectionTitle>
      <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
        <div><dt className="inline text-slate-500">Born </dt><dd className="inline">{s.dateOfBirth}{s.isMinor ? ", a minor" : ""}</dd></div>
        <div><dt className="inline text-slate-500">Nationalities </dt><dd className="inline">{s.nationality.join(", ") || "none given"}</dd></div>
        <div><dt className="inline text-slate-500">Eligibility </dt><dd className="inline">{BASES.find((b) => b.value === s.eligibilityBasis)?.label ?? s.eligibilityBasis}</dd></div>
        <div><dt className="inline text-slate-500">Club </dt><dd className="inline">{s.clubName} ({s.clubCountry}){s.competition ? `, ${s.competition}` : ""}</dd></div>
        <div><dt className="inline text-slate-500">Submitted by </dt><dd className="inline">{s.submittedByName ?? "a deleted account"} ({s.submitterRole})</dd></div>
        <div><dt className="inline text-slate-500">Position </dt><dd className="inline">{s.position ?? "not given"}</dd></div>
      </dl>
      <p className="mt-2 text-sm"><span className="text-slate-500">Source </span><SourceLink url={s.sourceUrl} /></p>
      {s.note ? <p className="mt-1 text-sm text-slate-300">{s.note}</p> : null}

      {s.seasons.length ? (
        <div className="mt-4">
          <Table>
            <thead>
              <tr>
                <Th>Season</Th>
                <Th>Group</Th>
                {COUNTS.map((c) => (
                  <Th key={c.key} className="text-right">{c.label}</Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {s.seasons.map((x) => (
                <tr key={`${x.competition}-${x.season}`}>
                  <Td>{x.competition} {x.season}</Td>
                  <Td>{String(x.metrics.position_group ?? "")}</Td>
                  {COUNTS.map((c) => (
                    <Td key={c.key} className="text-right tabular-nums">{x.metrics[c.key] ?? "n/a"}</Td>
                  ))}
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      ) : null}

      <div className="mt-5 flex flex-col gap-3">
        {s.checks.map((c) => (
          <div key={c.key} className="rounded-lg border border-slate-800 p-3">
            <p className="text-sm font-semibold text-slate-200">
              {c.label} <Chip tone={OUTCOME[c.outcome].tone}>{OUTCOME[c.outcome].label}</Chip>
            </p>
            <p className="text-sm text-slate-400">{c.summary}</p>
            {c.matches.length ? (
              <ul className="mt-2 flex flex-col gap-2">
                {c.matches.map((m) => (
                  <li key={`${c.key}-${m.kind}-${m.id}`} className="text-sm">
                    {m.kind === "player" ? (
                      <Link href={`/players/${m.id}`} className="text-sky-300 hover:underline"><bdi>{m.fullName}</bdi></Link>
                    ) : (
                      <span><bdi>{m.fullName}</bdi> (another open submission)</span>
                    )}
                    <span className="text-slate-400">
                      {m.dateOfBirth ? `, born ${m.dateOfBirth}` : ""}
                      {m.probability != null ? `, ${Math.round(m.probability * 100)}% likely the same person` : ""}
                    </span>
                    <span className="block text-xs text-slate-500">{m.evidence.join(". ")}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ))}
        <p className="text-xs text-slate-500">
          The probability is the identity engine&apos;s. On real records it has not been graded (decision 0010), so read the
          evidence, not just the number.
        </p>
      </div>

      {s.status === "awaiting_consent" ? (
        <div className="mt-5 rounded-lg border border-amber-900/70 p-3">
          <p className="text-sm text-amber-200">
            Waiting for the sign-up consent form{s.isMinor ? ", signed by a named guardian" : ""}. Nothing else can happen
            until it is recorded.
          </p>
          {s.isMinor ? (
            <Field label="Guardian who signed">
              <input className={inputClass} value={guardian} onChange={(e) => setGuardian(e.target.value)} />
            </Field>
          ) : null}
          <div className="mt-2">
            <Button disabled={busy || (s.isMinor && !guardian.trim())}
              onClick={() => void run(() => recordSubmissionConsent(s.id, s.isMinor ? guardian.trim() : null))}>
              Record the signed form
            </Button>
          </div>
        </div>
      ) : null}

      {s.mine ? (
        <p className="mt-5 text-sm text-slate-400">You submitted this one, so another member of the federation decides it.</p>
      ) : (
        <div className="mt-5 flex flex-col gap-3">
          <Field label="Decision">
            <select className={inputClass} value={action} onChange={(e) => setAction(e.target.value as typeof action)}>
              <option value="approve" disabled={s.status !== "pending"}>Approve: a new player</option>
              <option value="attach" disabled={s.status !== "pending" || !candidates.length}>
                Approve: the same person as a player on record
              </option>
              <option value="needs_info">Ask for more information</option>
              <option value="reject">Reject</option>
            </select>
          </Field>
          {action === "attach" ? (
            <Field label="Which player">
              <select className={inputClass} value={playerId} onChange={(e) => setPlayerId(e.target.value)}>
                <option value="">Pick one</option>
                {candidates.map((m) => (
                  <option key={m.id} value={m.id}>{m.fullName}{m.dateOfBirth ? `, born ${m.dateOfBirth}` : ""}</option>
                ))}
              </select>
            </Field>
          ) : null}
          <Field label="Reason" hint="Required. The submitter sees it. Say what you checked, and where.">
            <textarea className={inputClass} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          {problems.length ? (
            <Banner tone="bad" title="Not saved">
              <ul className="list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
            </Banner>
          ) : null}
          <div>
            <Button variant={action === "reject" ? "danger" : "primary"}
              disabled={busy || reason.trim().length < 5 || (action === "attach" && !playerId)}
              onClick={() => void run(() => decideSubmission(s.id, { action, reason: reason.trim(), playerId: playerId || undefined }))}>
              Save the decision
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
