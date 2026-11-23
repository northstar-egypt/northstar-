/**
 * Small hand-drawn national flags, for the Squad Lab player cards.
 *
 * Drawn here rather than taken from a flag package or emoji: emoji flags do not render on
 * Windows (they show two letters), and a dozen simple SVGs are less to maintain than a new
 * dependency. Details such as Egypt's eagle are simplified to shapes. A country not drawn
 * here falls back to its two-letter code, so a flag is never guessed.
 */

type Flag = (props: { className?: string }) => React.ReactElement;

const stripes = (colours: string[], vertical: boolean): Flag => {
  const Striped: Flag = ({ className }) => (
    <svg viewBox="0 0 30 20" className={className} aria-hidden>
      {colours.map((c, i) =>
        vertical ? (
          <rect
            key={i}
            x={(30 / colours.length) * i}
            y="0"
            width={30 / colours.length}
            height="20"
            fill={c}
          />
        ) : (
          <rect
            key={i}
            x="0"
            y={(20 / colours.length) * i}
            width="30"
            height={20 / colours.length}
            fill={c}
          />
        ),
      )}
    </svg>
  );
  return Striped;
};

const FLAGS: Record<string, Flag> = {
  EG: ({ className }) => (
    <svg viewBox="0 0 30 20" className={className} aria-hidden>
      <rect width="30" height="6.67" fill="#ce1126" />
      <rect y="6.67" width="30" height="6.67" fill="#fff" />
      <rect y="13.33" width="30" height="6.67" fill="#000" />
      <circle cx="15" cy="10" r="2.2" fill="#c09300" />
    </svg>
  ),
  IT: stripes(["#009246", "#fff", "#ce2b37"], true),
  FR: stripes(["#0055a4", "#fff", "#ef4135"], true),
  BE: stripes(["#000", "#fdda24", "#ef3340"], true),
  DE: stripes(["#000", "#dd0000", "#ffce00"], false),
  NL: stripes(["#ae1c28", "#fff", "#21468b"], false),
  CA: ({ className }) => (
    <svg viewBox="0 0 30 20" className={className} aria-hidden>
      <rect width="30" height="20" fill="#fff" />
      <rect width="7.5" height="20" fill="#d80621" />
      <rect x="22.5" width="7.5" height="20" fill="#d80621" />
      <path
        d="M15 4l1.2 2.6 2-.8-.7 3.4 1.8-.6-1 2.2 1 .6-3.5 1.3.3 2.3h-2.2l.3-2.3-3.5-1.3 1-.6-1-2.2 1.8.6-.7-3.4 2 .8z"
        fill="#d80621"
      />
    </svg>
  ),
  SA: ({ className }) => (
    <svg viewBox="0 0 30 20" className={className} aria-hidden>
      <rect width="30" height="20" fill="#006c35" />
      <rect x="8" y="7" width="14" height="2.2" rx="1" fill="#fff" />
      <rect x="9" y="12.5" width="12" height="1.2" fill="#fff" />
    </svg>
  ),
  AE: ({ className }) => (
    <svg viewBox="0 0 30 20" className={className} aria-hidden>
      <rect width="30" height="6.67" fill="#00732f" />
      <rect y="6.67" width="30" height="6.67" fill="#fff" />
      <rect y="13.33" width="30" height="6.67" fill="#000" />
      <rect width="8" height="20" fill="#ff0000" />
    </svg>
  ),
  QA: ({ className }) => (
    <svg viewBox="0 0 30 20" className={className} aria-hidden>
      <rect width="30" height="20" fill="#8a1538" />
      <path
        d="M0 0h9l3 1.1-3 1.1 3 1.1-3 1.1 3 1.1-3 1.1 3 1.1-3 1.1 3 1.1-3 1.1 3 1.1-3 1.1 3 1.1-3 1.1 3 1.1-3 1.1 3 1.1-3 1.1H0z"
        fill="#fff"
      />
    </svg>
  ),
  GB: ({ className }) => (
    <svg viewBox="0 0 30 20" className={className} aria-hidden>
      <rect width="30" height="20" fill="#012169" />
      <path d="M0 0l30 20M30 0L0 20" stroke="#fff" strokeWidth="4" />
      <path d="M0 0l30 20M30 0L0 20" stroke="#c8102e" strokeWidth="1.5" />
      <path d="M15 0v20M0 10h30" stroke="#fff" strokeWidth="6" />
      <path d="M15 0v20M0 10h30" stroke="#c8102e" strokeWidth="3.5" />
    </svg>
  ),
  US: ({ className }) => (
    <svg viewBox="0 0 30 20" className={className} aria-hidden>
      <rect width="30" height="20" fill="#fff" />
      {Array.from({ length: 7 }, (_, i) => (
        <rect
          key={i}
          y={(20 / 13) * i * 2}
          width="30"
          height={20 / 13}
          fill="#b22234"
        />
      ))}
      <rect width="12" height={(20 / 13) * 7} fill="#3c3b6e" />
    </svg>
  ),
};

export function FlagIcon({
  code,
  className,
}: {
  code: string;
  className?: string;
}) {
  const Drawn = FLAGS[code.toUpperCase()];
  if (Drawn) {
    return (
      <span
        title={code}
        className="inline-flex overflow-hidden rounded-[2px] ring-1 ring-black/40"
      >
        <Drawn className={className} />
      </span>
    );
  }
  return (
    <span
      title={code}
      className="rounded bg-slate-950/70 px-0.5 text-[0.55rem] font-semibold text-slate-300"
    >
      {code}
    </span>
  );
}
