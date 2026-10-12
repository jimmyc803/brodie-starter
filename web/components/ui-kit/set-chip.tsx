"use client";

import { useState } from "react";

import type { SetView } from "@/lib/contract";
import { setQuality, setSummary, type Quality } from "@/lib/quality";

const TONE: Record<Quality, string> = {
  good: "bg-good-soft text-good",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  none: "bg-idle-soft text-ink-2",
  skipped: "border border-dashed border-line-strong text-ink-3",
};

// One set: "9/10", colored by quality. Hover shows the full sentence, a tap opens it (phones have no hover),
// and screen readers read it instead of the bare numbers.
export function SetChip({ set, exerciseKey }: { set: SetView; exerciseKey: string }) {
  const [open, setOpen] = useState(false);
  const q = setQuality(set, exerciseKey);
  const summary = setSummary(set, exerciseKey);
  return (
    <span className="relative inline-block">
      <button
        type="button"
        title={summary}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onBlur={() => setOpen(false)}
        className={`min-w-11 rounded-md px-1.5 py-0.5 text-center text-xs font-semibold tabular-nums focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ink ${TONE[q]}`}
      >
        <span aria-hidden>{q === "skipped" ? "–" : `${set.completed_reps}/${set.planned_reps}`}</span>
        <span className="sr-only">{summary}</span>
      </button>
      {open ? (
        <span role="tooltip" className="absolute left-0 top-full z-20 mt-1 w-max max-w-56 rounded-[10px] bg-ink px-2.5 py-1.5 text-xs font-medium text-canvas shadow-lg">
          {summary}
        </span>
      ) : null}
    </span>
  );
}
