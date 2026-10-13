import { completedReps, plannedReps, topFaults, type ExerciseView } from "@/lib/contract";
import { formChecked } from "@/lib/quality";
import { SetChip } from "@/components/ui-kit/set-chip";

// One exercise: reps done / planned, a box per set, and what Brodie cued (or that form wasn't checked).
export function ExerciseCard({ exercise }: { exercise: ExerciseView }) {
  const done = completedReps(exercise);
  const planned = plannedReps(exercise);
  const checked = formChecked(exercise.exercise_key);
  const faults = topFaults(exercise.sets.flatMap((s) => s.reps));

  return (
    <article className="rounded-[14px] border border-line bg-surface px-4 py-3">
      <header className="flex items-baseline justify-between gap-3">
        <h3 className="text-[15px] font-semibold">{exercise.name}</h3>
        <p className="shrink-0 text-sm tabular-nums">
          <span className="font-semibold">{done}</span>
          <span className="text-ink-3">/{planned} reps</span>
        </p>
      </header>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {exercise.sets.map((s) => (
          <SetChip key={s.set_number} set={s} exerciseKey={exercise.exercise_key} />
        ))}
      </div>
      <p className="mt-2 text-[12.5px] text-ink-2">
        {!checked
          ? "Reps counted by camera · form not checked"
          : faults.length
            ? faults.map(([cue, n]) => `${cue} ×${n}`).join(" · ")
            : "No form flags"}
      </p>
    </article>
  );
}
