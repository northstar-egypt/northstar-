"use client";

/**
 * Add a player, then log a measurement. See docs/wireframes/03-add-edit-player.html.
 *
 * The only screen in the product designed for a phone first, because a coach uses it standing
 * on a pitch. Two behaviours here are deliberate and should survive review:
 *
 *   1. Minor status is computed from the date of birth and announced immediately, in place,
 *      before the coach can move on. Nobody should add a 13 year old without being told that
 *      consent is now required.
 *   2. Implausible values raise a question, never a block. A coach who genuinely measured a
 *      12 cm jump must be able to save it, because that is exactly the observation the late
 *      bloomer and anomaly detectors need. What must never happen is that it passes silently.
 */

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Banner, Button, Card, Chip, Label, SectionTitle, inputClass } from "@/components/ui";
import { createPlayer, logMeasurement } from "@/lib/api";
import { ageLabel, isMinorFrom } from "@/lib/format";

const POSITIONS = ["GK", "CB", "RB", "LB", "CM", "CDM", "CAM", "LW", "RW", "ST"];

/** Rough plausibility ceiling for adolescent growth, used to ask a question, not to reject. */
const MAX_CM_PER_MONTH = 2.5;

export default function NewPlayerPage() {
  const router = useRouter();
  const [step, setStep] = useState<1 | 2>(1);

  const [fullName, setFullName] = useState("");
  const [dob, setDob] = useState("");
  const [position, setPosition] = useState<string>("");
  const [nationalities, setNationalities] = useState<string[]>(["EGY"]);
  const [egyptEligible, setEgyptEligible] = useState(true);

  const [height, setHeight] = useState("");
  const [weight, setWeight] = useState("");
  const [measuredAt, setMeasuredAt] = useState(() => new Date().toISOString().slice(0, 10));
  const [confidence, setConfidence] = useState<"measured" | "estimated">("measured");
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);

  const minor = useMemo(() => (dob ? isMinorFrom(dob) : null), [dob]);
  const age = useMemo(() => ageLabel(dob), [dob]);

  // Previous reading is unknown for a brand new player, so the check here is against an
  // absolute range. On an existing player the same control compares against the last value.
  const heightNum = Number(height);
  const implausible =
    height !== "" && (Number.isNaN(heightNum) || heightNum < 100 || heightNum > 220);

  const canContinue = fullName.trim().length > 1 && dob !== "" && position !== "";
  const canSave = height !== "" && (!implausible || acknowledged);

  async function save() {
    setBusy(true);
    const { id } = await createPlayer({
      fullName,
      dateOfBirth: dob,
      position,
      nationality: nationalities,
      isEgyptEligible: egyptEligible,
      primarySport: "football",
      tier: "youth",
    });
    await logMeasurement(id, {
      measuredAt,
      metrics: [
        { metric: "height_cm", value: Number(height), unit: "cm", confidence },
        ...(weight ? [{ metric: "weight_kg", value: Number(weight), unit: "kg", confidence }] : []),
      ],
      acknowledgedWarning: implausible && acknowledged,
    });
    setBusy(false);
    router.push("/dashboard");
  }

  return (
    <div className="mx-auto flex max-w-md flex-col gap-5">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold tracking-tight">Add player</h1>
        <Label>Step {step} of 2</Label>
      </div>

      {step === 1 ? (
        <Card className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <Label>Full name</Label>
            <input
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className={inputClass}
              autoComplete="off"
            />
          </div>

          <div className="flex flex-col gap-1">
            <Label>Date of birth</Label>
            <input
              type="date"
              value={dob}
              onChange={(e) => {
                setDob(e.target.value);
                setAcknowledged(false);
              }}
              className={inputClass}
            />
            {age ? <span className="text-xs text-slate-500">{age} old today</span> : null}
          </div>

          {minor === true ? (
            <Banner tone="warn" title={`This player is a minor${age ? `, ${age}` : ""}`}>
              Guardian consent is required before this profile can be seen by scouts. You can add
              them now and capture consent on the next step.
            </Banner>
          ) : null}

          <div className="flex flex-col gap-1.5">
            <Label>Position</Label>
            <div className="flex flex-wrap gap-1.5">
              {POSITIONS.map((p) => (
                <Chip key={p} onClick={() => setPosition(p)} active={position === p}>
                  {p}
                </Chip>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Nationality</Label>
            <div className="flex flex-wrap gap-1.5">
              {nationalities.map((n) => (
                <Chip
                  key={n}
                  tone="brand"
                  onClick={() => setNationalities((xs) => xs.filter((x) => x !== n))}
                  title="Remove"
                >
                  {n} &times;
                </Chip>
              ))}
              {!nationalities.includes("ITA") ? (
                <Chip onClick={() => setNationalities((xs) => [...xs, "ITA"])}>add second</Chip>
              ) : null}
            </div>
            <span className="text-xs text-slate-500">
              An array because diaspora players are dual national.
            </span>
          </div>

          <label className="flex items-center justify-between rounded-md border border-slate-800 bg-slate-900/40 px-3 py-2">
            <span className="text-sm">Also eligible for Egypt</span>
            <input
              type="checkbox"
              checked={egyptEligible}
              onChange={(e) => setEgyptEligible(e.target.checked)}
              className="h-4 w-4 accent-sky-500"
            />
          </label>

          <Button variant="primary" disabled={!canContinue} onClick={() => setStep(2)}>
            Continue
          </Button>
        </Card>
      ) : (
        <Card className="flex flex-col gap-4">
          <div>
            <span className="text-sm font-semibold">{fullName}</span>
            <span className="block text-xs text-slate-500">
              {age} &middot; {position}
            </span>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Measured on</Label>
            <div className="flex flex-wrap items-center gap-1.5">
              <Chip
                onClick={() => setMeasuredAt(new Date().toISOString().slice(0, 10))}
                active={measuredAt === new Date().toISOString().slice(0, 10)}
              >
                today
              </Chip>
              <input
                type="date"
                value={measuredAt}
                onChange={(e) => setMeasuredAt(e.target.value)}
                className={`${inputClass} w-auto flex-1`}
              />
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <Label>Height</Label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                inputMode="decimal"
                value={height}
                onChange={(e) => {
                  setHeight(e.target.value);
                  setAcknowledged(false);
                }}
                className={`${inputClass} text-lg tabular-nums`}
              />
              <span className="text-sm text-slate-500">cm</span>
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <Label>Weight</Label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                inputMode="decimal"
                value={weight}
                onChange={(e) => setWeight(e.target.value)}
                className={`${inputClass} text-lg tabular-nums`}
              />
              <span className="text-sm text-slate-500">kg</span>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Confidence</Label>
            <div className="flex gap-1.5">
              <Chip onClick={() => setConfidence("measured")} active={confidence === "measured"}>
                measured
              </Chip>
              <Chip onClick={() => setConfidence("estimated")} active={confidence === "estimated"}>
                estimated
              </Chip>
            </div>
            <span className="text-xs text-slate-500">
              The maturity models treat these differently, so it is worth one tap.
            </span>
          </div>

          {implausible ? (
            <Banner tone="warn" title="Check this">
              <p className="mb-2">
                {Number.isNaN(heightNum)
                  ? "That is not a number."
                  : `${heightNum} cm is outside the plausible range for a player of this age.`}{" "}
                You can save it anyway, and the entry will be recorded as confirmed by you.
              </p>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="ghost" onClick={() => setHeight("")}>
                  Correct it
                </Button>
                <Button size="sm" onClick={() => setAcknowledged(true)} disabled={acknowledged}>
                  {acknowledged ? "Will save anyway" : "Save anyway"}
                </Button>
              </div>
            </Banner>
          ) : null}

          <div className="flex flex-col gap-2">
            <Button variant="primary" disabled={!canSave || busy} onClick={save}>
              {busy ? "Saving" : "Save player and measurement"}
            </Button>
            <Button variant="ghost" onClick={() => setStep(1)}>
              Back
            </Button>
          </div>

          <p className="text-center text-xs text-slate-600">
            Offline saving is drawn in the wireframe and not built. It needs a service worker, a
            local queue, and a conflict story, so it is a decision rather than a detail.
          </p>
        </Card>
      )}

      <Card className="border-dashed">
        <SectionTitle>Not built on this screen</SectionTitle>
        <ul className="flex list-disc flex-col gap-1 pl-4 text-xs text-slate-500">
          <li>Guardian consent capture, which should be part of step 2 when a player is a minor.</li>
          <li>Editing an existing player. Same form, loaded with values, once the API can serve one.</li>
          <li>
            The position list is hard coded here. It should come from the sport module, which is
            an open question in docs/schema.md.
          </li>
        </ul>
      </Card>
    </div>
  );
}
