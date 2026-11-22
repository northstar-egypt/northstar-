"use client";

/** Persistent reading direction for mixed Arabic/English records. Evaluated in design-review.mjs. */
import { useEffect, useState } from "react";

export function LayoutDirection() {
  const [direction, setDirection] = useState<"ltr" | "rtl">("ltr");
  useEffect(() => {
    let saved: string | null = null;
    try { saved = localStorage.getItem("northstar-layout"); } catch { /* Storage can be disabled. */ }
    const value = saved === "rtl" ? "rtl" : "ltr";
    setDirection(value);
    document.documentElement.dir = value;
  }, []);
  return (
    <button
      type="button"
      aria-label="Arabic right-to-left layout"
      aria-pressed={direction === "rtl"}
      className="ns-button rounded-lg border border-slate-700 px-3 text-sm text-slate-300 hover:bg-slate-800"
      onClick={() => {
        const next = direction === "ltr" ? "rtl" : "ltr";
        setDirection(next);
        document.documentElement.dir = next;
        try { localStorage.setItem("northstar-layout", next); } catch { /* Direction still works without storage. */ }
      }}
    >
      <span lang="ar">العربية</span><span aria-hidden="true"> / {direction.toUpperCase()}</span>
    </button>
  );
}
