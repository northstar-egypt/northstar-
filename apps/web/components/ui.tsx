/**
 * Interface primitives.
 *
 * Hand written rather than pulled from a component library. CLAUDE.md names shadcn/ui in the
 * stack but it is not installed, and adding it is a new core dependency, which the same file
 * says to ask about first. These cover what the eight screens need. If the team wants shadcn,
 * these are small enough to throw away.
 *
 * Colour convention, kept deliberately separate so state never fights brand:
 *   sky     brand and selection
 *   emerald good, healthy, current
 *   amber   needs attention
 *   rose    wrong, failed, critical
 */

import { cx } from "@/lib/format";

/* ------------------------------------------------------------------ layout */

export function Card({
  children,
  className,
  as: Tag = "div",
}: {
  children: React.ReactNode;
  className?: string;
  as?: "div" | "section" | "article";
}) {
  return (
    <Tag className={cx("rounded-lg border border-slate-800 bg-slate-900/50 p-4", className)}>
      {children}
    </Tag>
  );
}

export function SectionTitle({
  children,
  action,
}: {
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-xs font-medium uppercase tracking-[0.12em] text-slate-400">
        {children}
      </h2>
      {action}
    </div>
  );
}

export function Label({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[0.66rem] font-medium uppercase tracking-[0.12em] text-slate-500">
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ controls */

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "default" | "ghost" | "danger";
  size?: "sm" | "md";
};

export function Button({
  variant = "default",
  size = "md",
  className,
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-md border font-medium transition",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-400",
        "disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-1.5 text-sm",
        variant === "primary" &&
          "border-sky-500 bg-sky-500 text-slate-950 hover:bg-sky-400 hover:border-sky-400",
        variant === "default" &&
          "border-slate-700 bg-slate-800 text-slate-100 hover:bg-slate-700",
        variant === "ghost" &&
          "border-transparent bg-transparent text-slate-400 hover:bg-slate-800 hover:text-slate-100",
        variant === "danger" &&
          "border-rose-900 bg-rose-950 text-rose-200 hover:bg-rose-900",
        className,
      )}
    />
  );
}

export function Chip({
  children,
  tone = "default",
  onClick,
  active,
  title,
}: {
  children: React.ReactNode;
  tone?: "default" | "good" | "warn" | "bad" | "brand";
  onClick?: () => void;
  active?: boolean;
  title?: string;
}) {
  const tones = {
    default: "border-slate-700 text-slate-300",
    good: "border-emerald-800 bg-emerald-950/60 text-emerald-300",
    warn: "border-amber-800 bg-amber-950/60 text-amber-300",
    bad: "border-rose-900 bg-rose-950/60 text-rose-300",
    brand: "border-sky-800 bg-sky-950/60 text-sky-300",
  } as const;

  const cls = cx(
    "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs whitespace-nowrap",
    tones[tone],
    active && "border-sky-400 bg-sky-500/15 text-sky-200",
    onClick && "hover:border-slate-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400",
  );

  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={cls} title={title} aria-pressed={active}>
        {children}
      </button>
    );
  }
  return (
    <span className={cls} title={title}>
      {children}
    </span>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <Label>{label}</Label>
      {children}
      {hint ? <span className="text-xs text-slate-500">{hint}</span> : null}
    </label>
  );
}

export const inputClass =
  "w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 " +
  "placeholder:text-slate-600 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500";

/* ------------------------------------------------------------------ display */

export function Stat({
  label,
  value,
  tone = "default",
  hint,
}: {
  label: string;
  value: React.ReactNode;
  tone?: "default" | "good" | "warn" | "bad";
  hint?: string;
}) {
  const tones = {
    default: "text-slate-100",
    good: "text-emerald-400",
    warn: "text-amber-400",
    bad: "text-rose-400",
  } as const;
  return (
    <Card className="flex flex-col gap-0.5">
      <Label>{label}</Label>
      <span className={cx("text-2xl font-bold tabular-nums leading-tight", tones[tone])}>
        {value}
      </span>
      {hint ? <span className="text-xs text-slate-500">{hint}</span> : null}
    </Card>
  );
}

export function Banner({
  tone = "warn",
  title,
  children,
}: {
  tone?: "warn" | "info" | "bad";
  title?: string;
  children: React.ReactNode;
}) {
  const tones = {
    warn: "border-amber-900/70 bg-amber-950/40 text-amber-200",
    info: "border-sky-900/70 bg-sky-950/40 text-sky-200",
    bad: "border-rose-900/70 bg-rose-950/40 text-rose-200",
  } as const;
  return (
    <div className={cx("rounded-lg border-l-4 px-4 py-3 text-sm", tones[tone])}>
      {title ? <div className="mb-0.5 font-semibold">{title}</div> : null}
      <div className="text-slate-300">{children}</div>
    </div>
  );
}

export function Table({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] border-collapse text-sm">{children}</table>
    </div>
  );
}

export function Th({
  children,
  className,
}: {
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <th
      className={cx(
        "border-b border-slate-700 px-2 py-2 text-left text-[0.66rem] font-medium uppercase tracking-[0.1em] text-slate-500",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  className,
}: {
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <td className={cx("border-b border-slate-800/70 px-2 py-2.5 text-slate-300", className)}>
      {children}
    </td>
  );
}

export function Avatar({ size = 40 }: { size?: number }) {
  return (
    <div
      className="flex flex-none items-center justify-center rounded-full border border-dashed border-slate-700 bg-slate-800/60 text-[0.6rem] text-slate-600"
      style={{ width: size, height: size }}
      aria-hidden
    >
      {size >= 40 ? "photo" : ""}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded bg-slate-800/70", className)} />;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-800 px-4 py-10 text-center text-sm text-slate-500">
      {children}
    </div>
  );
}

/**
 * Marks a value the API does not really produce yet. Used sparingly, on the numbers a reviewer
 * would otherwise take at face value.
 */
export function Stub({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="border-b border-dotted border-slate-600"
      title="Synthetic value. This endpoint is not built yet, see lib/api.ts."
    >
      {children}
    </span>
  );
}
