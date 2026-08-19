/**
 * Synthetic fixtures for building screens against.
 *
 * EVERY NAME AND NUMBER IN THIS FILE IS INVENTED. None of it describes a real person. That is
 * a hard rule in this repository (see CLAUDE.md): no real player data, ever, not even as a
 * test fixture, because the repo is public and git history is permanent.
 *
 * These exist because the application track cannot wait for the synthetic data generator in
 * `data/pipelines/synthetic`, which is the data track's next task. When that generator lands,
 * this file should be deleted and the screens pointed at a seeded database instead. The shapes
 * here deliberately match `lib/types.ts` so that swap is a change in `lib/api.ts` only.
 *
 * The numbers are chosen to exercise the interface honestly rather than to flatter it:
 * a player with a stale record, a forecast whose band is too wide to rank on, a scout result
 * that is withheld for consent, and a duplicate pair that a reviewer could plausibly get wrong.
 */

import type {
  Comparison,
  IntegrityFlag,
  OversightSummary,
  ParsedQuery,
  PlayerProfile,
  Player,
  SearchResult,
  SessionUser,
  SquadRow,
  UserRole,
} from "./types";

const ORG = { id: "org-1", name: "Zamalek Academy" };

/* ------------------------------------------------------------------ session users */

export const DEMO_USERS: Record<UserRole, SessionUser> = {
  coach: {
    id: "u-coach",
    fullName: "Nour Farouk",
    email: "coach@example.eg",
    role: "coach",
    organizationId: ORG.id,
    organizationName: ORG.name,
  },
  scout: {
    id: "u-scout",
    fullName: "Tarek Halim",
    email: "scout@example.eg",
    role: "scout",
    organizationId: "org-9",
    organizationName: "Independent",
  },
  federation: {
    id: "u-fed",
    fullName: "Mona Abbas",
    email: "federation@example.eg",
    role: "federation",
    organizationId: "org-fed",
    organizationName: "Egyptian FA",
  },
  player: {
    id: "u-player",
    fullName: "Youssef Adel",
    email: "player@example.eg",
    role: "player",
    organizationId: ORG.id,
    organizationName: ORG.name,
    linkedPlayerId: "p-1",
  },
  admin: {
    id: "u-admin",
    fullName: "System Admin",
    email: "admin@example.eg",
    role: "admin",
    organizationId: null,
    organizationName: null,
  },
};

/* ------------------------------------------------------------------ players */

function player(
  id: string,
  fullName: string,
  dob: string,
  position: string,
  isMinor = true,
  extra: Partial<Player> = {},
): Player {
  return {
    id,
    fullName,
    dateOfBirth: dob,
    sex: "male",
    nationality: ["EGY"],
    isEgyptEligible: true,
    primarySport: "football",
    tier: "youth",
    position,
    isMinor,
    status: "active",
    ...extra,
  };
}

export const PLAYERS: Player[] = [
  player("p-1", "Youssef Adel", "2011-06-14", "ST"),
  player("p-2", "Karim Mansour", "2011-03-02", "CB"),
  player("p-3", "Omar Hegazy", "2011-09-21", "CM"),
  player("p-4", "Seif Elgamal", "2010-11-05", "GK"),
  player("p-5", "Mazen Roshdy", "2011-01-30", "LW"),
  player("p-6", "Adham Sabry", "2010-08-19", "RB"),
  player("p-7", "Zeyad Nabil", "2011-04-08", "CM"),
  player("p-8", "Hamza Lotfy", "2010-12-12", "ST"),
];

/* ------------------------------------------------------------------ squad */

export const SQUAD: SquadRow[] = [
  {
    player: PLAYERS[0],
    ageLabel: "14y 2m",
    heightCm: 168,
    daysSinceLastLog: 4,
    heightTrend: [158, 160, 162, 163, 166, 168],
    flags: [{ type: "late_bloomer", label: "late bloomer", confidence: 0.72 }],
    consentComplete: true,
  },
  {
    player: PLAYERS[1],
    ageLabel: "15y 5m",
    heightCm: 176,
    daysSinceLastLog: 104,
    heightTrend: [168, 170, 173, 175, 176, 176],
    flags: [{ type: "consent", label: "consent missing" }],
    consentComplete: false,
  },
  {
    player: PLAYERS[2],
    ageLabel: "14y 11m",
    heightCm: 161,
    daysSinceLastLog: 11,
    heightTrend: [154, 156, 157, 159, 160, 161],
    flags: [],
    consentComplete: true,
  },
  {
    player: PLAYERS[3],
    ageLabel: "15y 9m",
    heightCm: 181,
    daysSinceLastLog: 6,
    heightTrend: [172, 175, 177, 179, 180, 181],
    flags: [],
    consentComplete: true,
  },
  {
    player: PLAYERS[4],
    ageLabel: "15y 6m",
    heightCm: 170,
    daysSinceLastLog: 118,
    heightTrend: [163, 165, 167, 168, 169, 170],
    flags: [
      { type: "anomaly", label: "growth anomaly", confidence: 0.63 },
      { type: "consent", label: "consent missing" },
    ],
    consentComplete: false,
  },
  {
    player: PLAYERS[5],
    ageLabel: "16y 0m",
    heightCm: 174,
    daysSinceLastLog: 9,
    heightTrend: [169, 170, 171, 173, 173, 174],
    flags: [],
    consentComplete: true,
  },
  {
    player: PLAYERS[6],
    ageLabel: "15y 4m",
    heightCm: 165,
    daysSinceLastLog: 97,
    heightTrend: [158, 160, 161, 163, 164, 165],
    flags: [{ type: "consent", label: "consent missing" }],
    consentComplete: false,
  },
  {
    player: PLAYERS[7],
    ageLabel: "15y 8m",
    heightCm: 179,
    daysSinceLastLog: 15,
    heightTrend: [170, 172, 175, 177, 178, 179],
    flags: [{ type: "breakout", label: "breakout candidate", confidence: 0.81 }],
    consentComplete: true,
  },
];

/* ------------------------------------------------------------------ profile */

function growthFor(start: number, months: number, perMonth: number) {
  const measured: { date: string; value: number }[] = [];
  const base = new Date("2023-09-01");
  for (let i = 0; i < months; i += 1) {
    const d = new Date(base);
    d.setMonth(d.getMonth() + i * 2);
    measured.push({
      date: d.toISOString().slice(0, 10),
      value: Math.round((start + i * perMonth * 2) * 10) / 10,
    });
  }
  return measured;
}

function profileFor(row: SquadRow): PlayerProfile {
  const measured = growthFor((row.heightCm ?? 160) - 14, 9, 0.8);
  const last = measured[measured.length - 1];
  const lastDate = new Date(last.date);

  const forecast = [1, 2, 3, 4, 5, 6].map((i) => {
    const d = new Date(lastDate);
    d.setMonth(d.getMonth() + i * 3);
    const value = last.value + i * 2.1;
    const spread = 1.2 + i * 0.9;
    return {
      date: d.toISOString().slice(0, 10),
      value: Math.round(value * 10) / 10,
      lower: Math.round((value - spread) * 10) / 10,
      upper: Math.round((value + spread) * 10) / 10,
    };
  });

  const population = measured.map((m, i) => ({
    date: m.date,
    p25: 158 + i * 1.4,
    p50: 164 + i * 1.5,
    p75: 170 + i * 1.6,
  }));

  return {
    player: row.player,
    organizationName: ORG.name,
    ageLabel: row.ageLabel,
    latest: { heightCm: row.heightCm, weightKg: 54 },
    growth: { measured, forecast, population, unit: "cm" },
    maturity: {
      offsetYears: row.player.id === "p-1" ? -1.5 : 0.2,
      predictedAdultHeightCm: 182,
      errorCm: 4,
      method: "growth velocity, no skeletal age available",
    },
    percentiles: [
      { metric: "height_cm", label: "Height", value: row.heightCm ?? 0, unit: "cm", percentile: 38, population: "Egyptian academy players, same age and sex", higherIsBetter: true },
      { metric: "sprint_10m_s", label: "Sprint 10m", value: 1.78, unit: "s", percentile: 71, population: "Egyptian academy players, same age and sex", higherIsBetter: false },
      { metric: "goals_per_90", label: "Goals per 90", value: 0.9, unit: "", percentile: 84, population: "Egyptian academy forwards, same age", higherIsBetter: true },
      { metric: "minutes", label: "Minutes played", value: 1140, unit: "", percentile: 55, population: "Egyptian academy players, same age", higherIsBetter: true },
    ],
    performance: [
      {
        id: "pe-1", playerId: row.player.id, sport: "football", periodType: "season_aggregate",
        periodStart: "2025-08-01", periodEnd: "2026-05-31",
        metrics: { minutes: 1140, goals: 14, assists: 5, xg: 9.8, shots: 61, passes_completed: 402 },
        schemaRef: "football@1", source: "coach_logged", isValidated: true,
      },
      {
        id: "pe-2", playerId: row.player.id, sport: "football", periodType: "season_aggregate",
        periodStart: "2024-08-01", periodEnd: "2025-05-31",
        metrics: { minutes: 980, goals: 7, assists: 3, xg: 7.1, shots: 44, passes_completed: 351 },
        schemaRef: "football@1", source: "coach_logged", isValidated: true,
      },
    ],
    flags: row.flags.filter((f) => f.type !== "consent"),
    flagReason:
      row.player.id === "p-1"
        ? "Growth is tracking about two years behind the population curve for his age while output holds steady."
        : null,
    summary:
      "Output is running ahead of expected goals across two seasons, on a physical profile that is below the median for his age. The maturity estimate puts him behind his peers, so the gap between his size and his production is likely to narrow in his favour rather than against him. The wide forecast band means this is a signal to keep measuring, not a conclusion.",
    provenance: {
      measurementCount: 42,
      performanceCount: 2,
      consents: [
        { purpose: "data_storage", granted: true },
        { purpose: "analytics", granted: true },
        { purpose: "scouting_visibility", granted: row.consentComplete },
      ],
    },
    permissions: { canEdit: true, canLog: true, canSeeFlags: true },
  };
}

export function profile(playerId: string): PlayerProfile | null {
  const row = SQUAD.find((r) => r.player.id === playerId);
  return row ? profileFor(row) : null;
}

/* ------------------------------------------------------------------ search */

export const PARSED_QUERY: ParsedQuery = {
  chips: [
    { label: "position: ST", understood: true },
    { label: "age: under 16", understood: true },
    { label: "height percentile: low", understood: true },
    { label: "goals per 90: high", understood: true },
    { label: "left footed: no data", understood: false },
  ],
};

export const SEARCH_RESULTS: SearchResult[] = [
  {
    player: PLAYERS[0], organizationName: ORG.name, ageLabel: "14y 2m", heightCm: 168,
    matchScore: 0.94,
    highlights: ["late bloomer", "0.90 goals per 90", "38th pct height"],
    trend: [158, 160, 162, 163, 166, 168], withheld: false,
  },
  {
    player: PLAYERS[7], organizationName: ORG.name, ageLabel: "15y 8m", heightCm: 179,
    matchScore: 0.9,
    highlights: ["breakout candidate", "0.74 goals per 90"],
    trend: [170, 172, 175, 177, 178, 179], withheld: false,
  },
  {
    player: { ...player("p-20", "Withheld", "2010-05-01", "ST"), fullName: "Player name withheld" },
    organizationName: "Ismaily Academy", ageLabel: "15y", heightCm: null,
    matchScore: 0.88, highlights: [], trend: [], withheld: true,
    withheldReason: "This player is a minor and has not consented to scouting visibility.",
  },
  {
    player: player("p-21", "Nader Sami", "2010-02-11", "ST", true, { tier: "diaspora", nationality: ["EGY", "ITA"] }),
    organizationName: "Bologna Primavera", ageLabel: "16y 6m", heightCm: 177,
    matchScore: 0.79, highlights: ["Egypt eligible", "diaspora"],
    trend: [168, 171, 173, 175, 176, 177], withheld: false,
  },
];

/* ------------------------------------------------------------------ comparison */

export function comparison(basis: "age" | "maturity"): Comparison {
  const byAge = basis === "age";
  return {
    players: [
      { player: PLAYERS[0], ageLabel: "14y 2m", maturityOffsetYears: -1.5 },
      { player: PLAYERS[1], ageLabel: "14y 5m", maturityOffsetYears: 0.2 },
    ],
    basis,
    caveat: byAge
      ? "Comparing by chronological age. Youssef is about 18 months behind in maturity, so his physical numbers here understate him. Switch to maturity to see the difference."
      : "Comparing by maturity. Each player is measured against peers at the same developmental stage rather than the same birthday.",
    metrics: [
      { label: "Height", unit: "cm", higherIsBetter: true, values: byAge ? [168, 176] : [168, 172] },
      {
        label: "Predicted adult height", unit: "cm", higherIsBetter: true, values: [182, 181],
        indistinguishable: true,
        note: "Both estimates carry 4 cm of error, so this is not a difference.",
      },
      { label: "Goals per 90", unit: "", higherIsBetter: true, values: [0.9, 0.64] },
      { label: "xG per 90", unit: "", higherIsBetter: true, values: [0.71, 0.66] },
      { label: "Sprint 10m", unit: "s", higherIsBetter: false, values: [1.78, 1.84] },
      { label: "Maturity offset", unit: "yr", higherIsBetter: false, values: [-1.5, 0.2] },
    ],
    growth: [
      { playerId: "p-1", points: growthFor(154, 9, 0.8) },
      { playerId: "p-2", points: growthFor(162, 9, 0.75) },
    ],
  };
}

/* ------------------------------------------------------------------ oversight */

export const OVERSIGHT: OversightSummary = {
  sport: "football",
  playersTracked: 1284,
  academiesReporting: 37,
  stalePct: 22,
  openFlags: 14,
  byRegion: [
    { region: "Cairo", players: 412, populationM: 10.1 },
    { region: "Giza", players: 268, populationM: 9.2 },
    { region: "Alexandria", players: 176, populationM: 5.4 },
    { region: "Ismailia", players: 121, populationM: 1.3 },
    { region: "Beheira", players: 74, populationM: 6.6 },
    { region: "Sharqia", players: 58, populationM: 7.6 },
    { region: "Sohag", players: 21, populationM: 5.3 },
    { region: "Qena", players: 11, populationM: 3.2 },
  ],
  byAgeTier: [
    { age: 12, pro: 0, youth: 96, diaspora: 2 },
    { age: 13, pro: 0, youth: 141, diaspora: 3 },
    { age: 14, pro: 0, youth: 168, diaspora: 5 },
    { age: 15, pro: 0, youth: 174, diaspora: 6 },
    { age: 16, pro: 4, youth: 152, diaspora: 7 },
    { age: 17, pro: 18, youth: 96, diaspora: 5 },
    { age: 18, pro: 41, youth: 44, diaspora: 4 },
  ],
  academies: [
    {
      organization: { id: "org-4", name: "Delta Youth FC", type: "academy", sport: "football", country: "EG", region: "Beheira" },
      playerCount: 41, lastSubmissionDays: 118, medianStalenessDays: 134, consentCompletePct: 52, openFlags: 3,
    },
    {
      organization: { id: "org-5", name: "Upper Egypt Sports Club", type: "academy", sport: "football", country: "EG", region: "Sohag" },
      playerCount: 19, lastSubmissionDays: 96, medianStalenessDays: 110, consentCompletePct: 61, openFlags: 2,
    },
    {
      organization: { id: "org-3", name: "Ismaily Academy", type: "academy", sport: "football", country: "EG", region: "Ismailia" },
      playerCount: 63, lastSubmissionDays: 21, medianStalenessDays: 29, consentCompletePct: 88, openFlags: 1,
    },
    {
      organization: { id: "org-1", name: "Zamalek Academy", type: "academy", sport: "football", country: "EG", region: "Cairo" },
      playerCount: 96, lastSubmissionDays: 4, medianStalenessDays: 11, consentCompletePct: 94, openFlags: 2,
    },
  ],
  diaspora: { total: 28, uncappedUnder21: 6, newThisMonth: 3 },
};

/* ------------------------------------------------------------------ integrity */

export const FLAGS: IntegrityFlag[] = [
  {
    id: "f-1", type: "duplicate", status: "open",
    playerName: "Ahmed Sayed", organizationName: "Delta Youth FC",
    raisedAt: "2026-08-17", ageDays: 2, confidence: 0.91,
    reason: "Same date of birth, names match closely, both at Delta Youth FC, affiliations overlap, and eleven measurement dates coincide.",
    evidence: [
      "Date of birth identical",
      "Name similarity 0.88",
      "Same organization, overlapping affiliation dates",
      "11 measurement dates coincide",
    ],
    records: {
      label: "Ahmed Sayed", playerId: "p-30", createdAt: "2025-03-12", measurementCount: 34, source: "coach logged",
      fields: [
        { field: "Full name", a: "Ahmed Sayed", b: "Ahmed S. Ibrahim", differs: true },
        { field: "Date of birth", a: "2011-02-19", b: "2011-02-19", differs: false },
        { field: "Position", a: "CM", b: "CM", differs: false },
        { field: "Organization", a: "Delta Youth FC", b: "Delta Youth FC", differs: false },
        { field: "Created", a: "12 Mar 2025", b: "2 Sep 2025", differs: true },
        { field: "Measurements", a: "34", b: "8", differs: true },
        { field: "Source", a: "coach logged", b: "bulk import", differs: true },
      ],
    },
    history: [
      { at: "2 days ago", who: "system", what: "flag raised, confidence 0.91" },
      { at: "1 day ago", who: "N. Farouk", what: "opened, no decision" },
    ],
  },
  {
    id: "f-2", type: "fraud", status: "open",
    playerName: "Mostafa Kamel", organizationName: null,
    raisedAt: "2026-08-15", ageDays: 4, confidence: 0.77,
    reason: "Self submitted results improve faster than any comparable player in the table tennis dataset, and all entries were submitted in a single session.",
    evidence: [
      "Win rate rose from 0.41 to 0.86 in six weeks",
      "All 14 entries submitted within 20 minutes",
      "No corroborating ITTF result for 9 of 14 entries",
    ],
    records: null,
    history: [{ at: "4 days ago", who: "system", what: "flag raised, confidence 0.77" }],
  },
  {
    id: "f-3", type: "anomaly", status: "open",
    playerName: "Hassan Yehia", organizationName: "Ismaily Academy",
    raisedAt: "2026-08-10", ageDays: 9, confidence: 0.58,
    reason: "Recorded 12 cm of height growth in 24 days, which is outside the plausible range for any adolescent.",
    evidence: [
      "Height 166 cm to 178 cm in 24 days",
      "Previous 12 months averaged 0.7 cm per month",
      "Coach confirmed the value on save",
    ],
    records: null,
    history: [
      { at: "9 days ago", who: "system", what: "flag raised, confidence 0.58" },
      { at: "9 days ago", who: "system", what: "coach was warned at entry and saved anyway" },
    ],
  },
];
