import { completedReps, plannedReps, topFaults, type SessionView } from "@/lib/contract";
import { formChecked } from "@/lib/quality";

// Brodie's one-line take on a session for the client recap: the most common form cue on an exercise he checks,
// or praise / a nudge to finish when there's nothing to fix.
export function brodieLine(view: SessionView): string {
  const done = view.exercises.reduce((n, ex) => n + completedReps(ex), 0);
  if (done === 0) return "No reps counted this time. Prop the phone up so I can see you, and let's go again.";
  const complete = view.exercises.every((ex) => completedReps(ex) >= plannedReps(ex));
  let top: { exercise: string; cue: string; n: number } | null = null;
  for (const ex of view.exercises) {
    if (!formChecked(ex.exercise_key)) continue;
    const [first] = topFaults(ex.sets.flatMap((s) => s.reps), 1);
    if (first && (!top || first[1] > top.n)) top = { exercise: ex.name, cue: first[0], n: first[1] };
  }
  if (top) {
    const cue = top.cue.replace(/[.!]+$/, "");
    return `${complete ? "Every set done." : "Solid effort."} Next time on ${top.exercise.toLowerCase()}: ${cue.charAt(0).toLowerCase()}${cue.slice(1)}.`;
  }
  return complete ? "Every set done, clean form. That's how it's done." : "Clean form. Finish every set next time.";
}
