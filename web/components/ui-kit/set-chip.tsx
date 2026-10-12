import type { SetView } from "@/lib/contract";
import { setQuality, setSummary, type Quality } from "@/lib/quality";

const TONE: Record<Quality, string> = {
  good: "bg-good-soft text-good",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  none: "bg-idle-soft text-ink-2",
  skipped: "border border-dashed border-line-strong text-ink-3",
};

// One set: "9/10", colored by quality; hover (or a screen reader) gets the full sentence.
export function SetChip({ set, exerciseKey }: { set: SetView; exerciseKey: string }) {
  const q = setQuality(set, exerciseKey);
  const summary = setSummary(set, exerciseKey);
  return (
    <span title={summary} aria-label={summary} className={`inline-block min-w-11 rounded-md px-1.5 py-0.5 text-center text-xs font-semibold tabular-nums ${TONE[q]}`}>
      {q === "skipped" ? "–" : `${set.completed_reps}/${set.planned_reps}`}
    </span>
  );
}
