/**
 * Each role's light identity: an accent colour, how its home greets it, and the words of its
 * job. One product, so the components and layout are shared; what changes is the colour a role
 * lives in and the first thing it is told.
 *
 * Tailwind only keeps classes it can see written out, so every class is spelled in full here
 * rather than built from the colour's name.
 */

import type { UserRole } from "./types";

export interface RoleIdentity {
  /** What the role is called on screen. */
  title: string;
  /** The home's heading, given the user's first name (or null). */
  greeting: (firstName: string | null) => string;
  /** One line under the greeting: what this home is for. */
  tagline: string;
  /** A thin bar under the nav, and the mark beside "NorthStar". */
  bar: string;
  mark: string;
  /** The active nav link. */
  active: string;
  /** Headings and figures that carry the role's colour. */
  text: string;
  /** A card edge that carries it. */
  border: string;
}

export const ROLE_IDENTITY: Record<UserRole, RoleIdentity> = {
  scout: {
    title: "Scout",
    greeting: (name) => (name ? `Good hunting, ${name}` : "Good hunting"),
    tagline: "Your shortlist, and who stepped up since you last looked.",
    bar: "bg-amber-400",
    mark: "bg-amber-400",
    active: "bg-amber-400/15 font-semibold text-amber-200",
    text: "text-amber-300",
    border: "border-amber-500/40",
  },
  coach: {
    title: "Coach",
    greeting: (name) => (name ? `Your squad, coach ${name}` : "Your squad"),
    tagline: "Who needs measuring, and who is growing.",
    bar: "bg-emerald-400",
    mark: "bg-emerald-400",
    active: "bg-emerald-400/15 font-semibold text-emerald-200",
    text: "text-emerald-300",
    border: "border-emerald-500/40",
  },
  federation: {
    title: "Federation",
    greeting: (name) => (name ? `The national picture, ${name}` : "The national picture"),
    tagline: "Talent across the country, and what needs a decision.",
    bar: "bg-violet-400",
    mark: "bg-violet-400",
    active: "bg-violet-400/15 font-semibold text-violet-200",
    text: "text-violet-300",
    border: "border-violet-500/40",
  },
  player: {
    title: "Player",
    greeting: (name) => (name ? `Your journey, ${name}` : "Your journey"),
    tagline: "Your growth, your progress, and who can see your data.",
    bar: "bg-rose-400",
    mark: "bg-rose-400",
    active: "bg-rose-400/15 font-semibold text-rose-200",
    text: "text-rose-300",
    border: "border-rose-500/40",
  },
  admin: {
    title: "Admin",
    greeting: () => "Administration",
    tagline: "Accounts and the integrity board.",
    bar: "bg-sky-400",
    mark: "bg-sky-400",
    active: "bg-slate-800 font-semibold text-slate-100",
    text: "text-sky-300",
    border: "border-sky-500/40",
  },
};
