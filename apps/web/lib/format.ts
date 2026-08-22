/** Small formatting helpers shared across screens. No dependencies on purpose. */

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/** Formats a number for display, keeping digits column friendly. */
export function num(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "no data";
  return value.toLocaleString("en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/** 1st, 2nd, 3rd, 38th. Percentiles read badly without the suffix. */
export function ordinal(n: number): string {
  const rounded = Math.round(n);
  const mod100 = rounded % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${rounded}th`;
  switch (rounded % 10) {
    case 1: return `${rounded}st`;
    case 2: return `${rounded}nd`;
    case 3: return `${rounded}rd`;
    default: return `${rounded}th`;
  }
}

export function daysLabel(days: number | null): string {
  if (days === null) return "never";
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

/**
 * Staleness thresholds. Ninety days is a placeholder, not a decision: see the open question in
 * `docs/wireframes/02-coach-dashboard.html`. It probably differs between a youth academy and a
 * professional club.
 */
export const STALE_DAYS = 90;

export function isStale(days: number | null): boolean {
  return days === null || days >= STALE_DAYS;
}

/** Age from a date of birth, as "14y 2m". Returns null when the source hid the date. */
export function ageLabel(dateOfBirth: string | null | undefined, now = new Date()): string | null {
  if (!dateOfBirth) return null;
  const dob = new Date(dateOfBirth);
  if (Number.isNaN(dob.getTime())) return null;
  let months = (now.getFullYear() - dob.getFullYear()) * 12 + (now.getMonth() - dob.getMonth());
  if (now.getDate() < dob.getDate()) months -= 1;
  if (months < 0) return null;
  return `${Math.floor(months / 12)}y ${months % 12}m`;
}

/** True when the player is under 18 today. The API is authoritative; this is for the entry form. */
export function isMinorFrom(dateOfBirth: string, now = new Date()): boolean | null {
  const dob = new Date(dateOfBirth);
  if (Number.isNaN(dob.getTime())) return null;
  const eighteenth = new Date(dob);
  eighteenth.setFullYear(eighteenth.getFullYear() + 18);
  return now < eighteenth;
}

export function shortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { month: "short", year: "numeric" });
}
