/**
 * A football pitch with the zone a position group plays in, for the scouting report. It shows the
 * role the player is graded as, not where this player actually stood: there is no event or
 * tracking data behind it, and the caption says so. Attack is to the right.
 *
 * Zones are keyed by the position groups in packages/shared/sports/football.json. An unknown
 * group draws the pitch with no zone rather than guessing one.
 */

type Zone = { x: number; y: number; w: number; h: number };

// Pitch units: 105 by 68 metres.
const ZONES: Record<string, { zones: Zone[]; where: string }> = {
  centre_backs: { zones: [{ x: 5, y: 17, w: 28, h: 34 }], where: "in the centre of defence" },
  full_backs: {
    zones: [
      { x: 8, y: 2, w: 52, h: 14 },
      { x: 8, y: 52, w: 52, h: 14 },
    ],
    where: "on either flank, from defence to beyond halfway",
  },
  holding_midfielders: { zones: [{ x: 28, y: 18, w: 24, h: 32 }], where: "just in front of the defence" },
  central_midfielders: { zones: [{ x: 38, y: 14, w: 32, h: 40 }], where: "in the centre of the pitch" },
  wingers: {
    zones: [
      { x: 58, y: 2, w: 42, h: 15 },
      { x: 58, y: 51, w: 42, h: 15 },
    ],
    where: "on either wing, in the final third",
  },
  strikers: { zones: [{ x: 78, y: 19, w: 25, h: 30 }], where: "in and around the opposition box" },
};

export function Pitch({
  group,
  groupLabel,
  className,
}: {
  group: string;
  groupLabel: string;
  /** Sets the zone colour through `currentColor`, e.g. a role's text colour. */
  className?: string;
}) {
  const role = ZONES[group];
  const line = "rgba(148, 163, 184, 0.45)";
  return (
    <figure className={className}>
      <svg viewBox="-2 -2 109 76" className="h-auto w-full" role="img" aria-label={`Pitch: ${groupLabel} play ${role?.where ?? "in an unmarked zone"}`}>
        <defs>
          <pattern id="pitch-stripes" width="10.5" height="68" patternUnits="userSpaceOnUse">
            <rect width="5.25" height="68" fill="#0b1f17" />
            <rect x="5.25" width="5.25" height="68" fill="#0d2419" />
          </pattern>
          <filter id="pitch-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="2.2" />
          </filter>
        </defs>
        <rect x="0" y="0" width="105" height="68" rx="1" fill="url(#pitch-stripes)" />

        {role?.zones.map((z, i) => (
          <g key={i}>
            <rect x={z.x} y={z.y} width={z.w} height={z.h} rx="4" fill="currentColor" opacity="0.35" filter="url(#pitch-glow)" />
            <rect
              x={z.x}
              y={z.y}
              width={z.w}
              height={z.h}
              rx="4"
              fill="currentColor"
              fillOpacity="0.28"
              stroke="currentColor"
              strokeWidth="0.5"
              strokeDasharray="1.5 1"
            />
          </g>
        ))}

        <g fill="none" stroke={line} strokeWidth="0.35">
          <rect x="0" y="0" width="105" height="68" />
          <line x1="52.5" y1="0" x2="52.5" y2="68" />
          <circle cx="52.5" cy="34" r="9.15" />
          <rect x="0" y="13.84" width="16.5" height="40.32" />
          <rect x="88.5" y="13.84" width="16.5" height="40.32" />
          <rect x="0" y="24.84" width="5.5" height="18.32" />
          <rect x="99.5" y="24.84" width="5.5" height="18.32" />
          <path d="M16.5,26.7 A9.15,9.15 0 0 1 16.5,41.3" />
          <path d="M88.5,26.7 A9.15,9.15 0 0 0 88.5,41.3" />
          <rect x="-1.5" y="30.34" width="1.5" height="7.32" />
          <rect x="105" y="30.34" width="1.5" height="7.32" />
        </g>
        <g fill={line}>
          <circle cx="52.5" cy="34" r="0.5" />
          <circle cx="11" cy="34" r="0.4" />
          <circle cx="94" cy="34" r="0.4" />
        </g>
        <g fill="rgba(148, 163, 184, 0.7)" fontSize="2.6">
          <text x="0" y="72.5">own goal</text>
          <text x="105" y="72.5" textAnchor="end">attacking &rarr;</text>
        </g>
      </svg>
      <figcaption className="mt-1.5 text-xs text-slate-500">
        {role
          ? `Graded as one of the ${groupLabel.toLowerCase()}, who play ${role.where}. The role's zone, not a map of this player's touches: there is no event data.`
          : `Graded as one of the ${groupLabel.toLowerCase()}.`}
      </figcaption>
    </figure>
  );
}
