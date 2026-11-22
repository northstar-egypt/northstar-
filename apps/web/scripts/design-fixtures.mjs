/** Invented view models for design review only. Used by design-review.mjs; never imported by the app. */
const player = (id, fullName) => ({ id, fullName, dateOfBirth: "2011-04-12", sex: "male", nationality: ["EG"], isEgyptEligible: true, primarySport: "football", tier: "youth", position: "Midfielder", isMinor: true, status: "active" });
const players = [player("design-1", "يوسف نور التجريبي"), player("design-2", "Omar Design Example")];
const dates = ["2025-01-01", "2025-04-01", "2025-07-01", "2025-10-01", "2026-01-01", "2026-04-01"];
const profile = {
  player: players[0], organizationName: "Design Academy (invented)", ageLabel: "15y 7m", latest: { heightCm: 164, weightKg: 52 },
  growth: { measured: dates.map((date, i) => ({ date, value: 150 + i * 2.8 })), forecast: [{ date: "2026-07-01", value: 166, lower: 163, upper: 169 }, { date: "2026-10-01", value: 168, lower: 164, upper: 172 }], population: dates.map((date, i) => ({ date, p25: 148 + i * 2, p50: 154 + i * 2, p75: 160 + i * 2 })), unit: "cm", forecastNote: "Invented visual fixture. 80% forecast band." },
  maturity: { offsetYears: -0.8, predictedAdultHeightCm: 179, errorCm: 4, method: "Invented review fixture" },
  percentiles: [{ metric: "sprint", label: "Sprint", value: 4.2, unit: "s", percentile: 68, population: "30 invented midfielders", higherIsBetter: false }],
  performance: [], flags: [{ type: "late_bloomer", label: "Potential late bloomer" }], flagReason: "Invented fixture for visual review, not a real player assessment.",
  provenance: { measurementCount: 6, performanceCount: 0, consents: [{ purpose: "analytics", granted: true }] }, permissions: { canEdit: true, canLog: true, canSeeFlags: true },
};
const card = (p) => ({ playerId: p.id, fullName: p.fullName, position: p.position, tier: p.tier, ageLabel: "15y 7m", club: "Design Academy (invented)", isMinor: true });
const evidence = (key, label, percentile) => ({ key, label, value: 0.45, unit: "per 90", percentile, median: 0.3, lowReliability: false });
const report = {
  playerId: "design-1", season: "2025/26", competition: "Invented Review League", club: "Design Academy", group: "midfielders", groupLabel: "Midfielders", minutes: 1800, population: 32,
  level: 72, levelGrade: "B", recommendation: "Shortlist", confidence: "medium",
  areas: [{ key: "attack", label: "Attacking", score: 78, grade: "B", graded: true, evidence: [evidence("goals", "Goals per 90", 82), evidence("assists", "Assists per 90", 74)] }, { key: "defence", label: "Defending", score: 55, grade: "C", graded: false, evidence: [evidence("duels", "Duels won per 90", 55)] }],
  strengths: [], weaknesses: [], summary: "Invented visual review fixture, not a real scouting assessment.", wouldChange: ["More minutes in a comparable competition."], notInData: ["Personality, injury history and training observations are not known."], young: true,
  finishing: { npGoals: 8, npxg: 6.4, low: 3, high: 10, verdict: "in line", seasons: 1 }, breakout: null,
  case: [{ kind: "strength", headline: "Attacking contribution", detail: "82nd percentile on the invented goals metric." }, { kind: "caution", headline: "Keep uncertainty visible", detail: "Medium confidence from 1,800 invented minutes." }],
  seasons: [{ competition: "Invented Review League", season: "2025/26", club: "Design Academy", minutes: 1800, gradable: true, selected: true, goals: 8, assists: 6, npxg: 6.4, xa: 4.5 }],
  similar: [{ ...card(players[1]), competition: "Invented Review League", season: "2025/26", minutes: 1600, similarity: 76 }],
  pitch: { shots: [{ x: 85, y: 40, outcome: "goal", xg: 0.2, situation: "open_play" }, { x: 80, y: 55, outcome: "saved", xg: 0.1, situation: "open_play" }], keyPasses: [{ x: 70, y: 35, endX: 90, endY: 45, outcome: "assist", xa: 0.2 }], touchMap: Array.from({ length: 96 }, (_, i) => i % 7), matches: 20, eventSource: "synthetic visual fixture", xgModel: null },
};

export function fixture(path, role, state = "normal") {
  const p = path.split("?")[0];
  if (p === "/me") return { id: "design-review", fullName: "Design Reviewer", email: "review@example.invalid", role, organizationId: "design-org", organizationName: "Design Academy (invented)" };
  if (p === "/dev/identities") return [];
  if (p.startsWith("/health")) return { status: "ok", database: "synthetic visual fixture" };
  if (p === "/sports") return [{ sport: "football", label: "Football", roleLabel: "Position", roles: ["Goalkeeper", "Defender", "Midfielder", "Forward"], genders: ["male"], usesTier: true, events: [] }];
  if (p === "/players") return state === "empty" ? [] : players.map((p, i) => ({ player: p, ageLabel: "15y 7m", heightCm: 164 + i, daysSinceLastLog: 120 + i, heightTrend: [150, 153, 156, 159, 162, 164], heightReadings: 6, growthCmPerYear: 5.6, heightReadingsNeeded: 0, flags: i ? [] : profile.flags, consentComplete: true }));
  if (p === "/squad/measuring-plan") return { capacity: 2, suggested: 2, squad: 2, plannedFrom: 2, withoutConsent: 0, players: state === "empty" ? [] : players.map(p => ({ player: p, ageLabel: "15y 7m", readingsLastYear: 4, daysSinceLast: 120, reasons: ["Overdue for a reading"] })) };
  if (p.endsWith("/profile")) return state === "missing" ? { ...profile, latest: { heightCm: null, weightKg: null }, growth: { measured: [], forecast: [], population: [], unit: "cm", forecastNote: "Not enough readings for a forecast." }, maturity: null, percentiles: [], flags: [] } : profile;
  if (p.endsWith("/scouting-report")) return state === "insufficient" ? { report: null, note: "Not enough minutes to grade." } : { report, note: "Synthetic visual fixture" };
  if (p.endsWith("/summary")) return { summary: null, note: "Assistant is not running in this visual fixture.", model: null };
  if (p.endsWith("/pro-seasons")) return { seasons: [], career: null, trends: [], note: "No pro seasons in this youth fixture." };
  if (p.endsWith("/estimates")) return { seasons: [], note: "Not enough comparable records." };
  if (p.endsWith("/radar")) return { axes: [], population: null, note: "Not enough comparable players." };
  if (p.endsWith("/similar")) return { items: [], note: "Not enough comparable records." };
  if (p.endsWith("/events")) return { events: [], summary: [], note: "No tagged events." };
  if (p === "/shortlist") return { playerIds: [] };
  if (p === "/home/scout") return { firstName: "Reviewer", shortlist: state === "empty" ? [] : [{ ...card(players[0]), note: "Watch the next measurement", savedAt: "2026-11-20" }], withheld: 0, breakouts: [], breakoutSeason: null, lateBloomers: state === "empty" ? [] : [{ ...card(players[0]), reason: profile.flagReason, status: "open" }] };
  if (p === "/search") return { parsed: { chips: [{ label: "Youth tier", understood: true }] }, results: state === "empty" ? [] : players.map(p => ({ player: p, organizationName: "Design Academy (invented)", ageLabel: "15y 7m", heightCm: 164, matchScore: 0.8, highlights: ["Invented visual fixture"], trend: [150, 153, 158, 164], withheld: false })), total: state === "empty" ? 0 : 2 };
  if (p === "/compare") return { players: players.map(player => ({ player, ageLabel: "15y 7m", maturityOffsetYears: -0.8 })), basis: "age", caveat: "Invented data. Differences are smaller than the uncertainty.", metrics: [{ label: "Height", unit: "cm", higherIsBetter: true, values: [164, 165], indistinguishable: true }], growth: players.map(player => ({ playerId: player.id, points: dates.map((date, i) => ({ date, value: 150 + i * 2.8 })) })) };
  if (p === "/gaps") return { clubs: state === "empty" ? [] : [{ id: "design-club", name: "Design Academy (invented)", competition: "Review League", seasons: ["2025/26"] }], groups: [{ key: "midfielders", label: "Midfielders", attributes: ["assists"] }], attributes: [{ key: "assists", label: "Assists per 90", lowReliability: false, percent: false }], minMinutes: 450, minCohort: 20 };
  if (p.startsWith("/gaps/club/")) return { club: { id: "design-club", name: "Design Academy", competition: "Review League", season: "2025/26" }, profile: [], coverage: [], minMinutes: 450 };
  if (p === "/gaps/national") return { needs: [], minMinutes: 450 };
  if (p === "/oversight") return { sport: "football", playersTracked: 2, academiesReporting: 1, stalePct: 1, openFlags: 1, byRegion: [], playersWithoutGovernorate: 2, byAgeTier: [{ age: 15, youth: 2, pro: 0, diaspora: 0, other: 0 }], academies: [], diaspora: { total: 0, under21: 0, newThisMonth: 0 } };
  if (p === "/oversight/strongest") return [];
  if (p === "/integrity/counts") return { fraud: 0, duplicate: 1, anomaly: 0 };
  if (p === "/integrity/flags") return state === "empty" ? [] : [{ id: "design-flag", type: "duplicate", status: "open", playerName: players[0].fullName, organizationName: "Design Academy", raisedAt: "2026-11-20", ageDays: 2, detector: "synthetic fixture", confidence: null, reason: "Possible repeated registration. Review both records before deciding.", evidence: ["Invented inputs for visual review only"], history: [] }];
  return null;
}
