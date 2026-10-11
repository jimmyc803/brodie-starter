import {
  COLORS,
  completedReps,
  faultyReps,
  plannedReps,
  setReached,
  topFaults,
  type Color,
  type ExerciseView,
  type SetView,
} from "@/lib/contract";

// Share of clean reps in a set -> bar color: green solid, yellow room to improve, red needs work.
function setColor(s: SetView): Color {
  if (!s.completed_reps) return "gray";
  const clean = Math.max(0, s.completed_reps - faultyReps(s)) / s.completed_reps;
  if (clean >= 0.8) return "green";
  if (clean >= 0.5) return "yellow";
  return "red";
}

// One set as a small tile: reps on top, a thin bar for planned vs completed, flagged reps underneath.
function SetTile({ set }: { set: SetView }) {
  const reached = setReached(set);
  const pct = set.planned_reps ? Math.min(100, (set.completed_reps / set.planned_reps) * 100) : 0;
  const flagged = faultyReps(set);
  return (
    <li className="min-w-0" aria-label={`Set ${set.set_number}`}>
      <div className="flex items-baseline justify-between gap-1 t-caption text-ink-3">
        <span className="font-medium">Set {set.set_number}</span>
        {reached ? (
          <span className="tabular-nums">
            <span className="t-callout font-semibold text-ink">{set.completed_reps}</span>/{set.planned_reps}
          </span>
        ) : null}
      </div>
      {reached ? (
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-fill" aria-hidden>
          <div className="h-full rounded-full" style={{ width: `${pct}%`, background: COLORS[setColor(set)] }} />
        </div>
      ) : (
        <div className="mt-1 h-1.5 rounded-full border border-dashed border-ink-3" aria-hidden />
      )}
      <div className="mt-1 truncate t-caption text-ink-3">
        {!reached ? "not reached" : flagged ? `${flagged} flagged` : "clean"}
      </div>
    </li>
  );
}

export function ExerciseCard({ exercise }: { exercise: ExerciseView }) {
  const done = completedReps(exercise);
  const planned = plannedReps(exercise);
  const faults = topFaults(exercise.sets.flatMap((s) => s.reps));

  return (
    <li className="px-4 py-4 sm:px-5">
      <header className="flex items-baseline justify-between gap-3">
        <h3 className="t-headline">{exercise.name}</h3>
        <p className="shrink-0 tabular-nums">
          <span className="t-headline">{done}</span>
          <span className="t-callout text-ink-3">/{planned}</span>
          <span className="ml-1 t-caption text-ink-3">reps</span>
        </p>
      </header>

      <ul
        className="mt-3 grid gap-3"
        style={{ gridTemplateColumns: `repeat(${Math.max(1, exercise.sets.length)}, minmax(0, 1fr))` }}
      >
        {exercise.sets.map((s) => (
          <SetTile key={s.set_number} set={s} />
        ))}
      </ul>

      <ul className="mt-3 flex flex-wrap gap-x-3 gap-y-1" aria-label="Brodie's cues">
        {faults.length ? (
          faults.map(([cue, n]) => (
            <li
              key={cue}
              className="t-footnote text-ink-2"
            >
              {cue} <span className="tabular-nums text-ink-3">×{n}</span>
            </li>
          ))
        ) : (
          <li className="t-footnote text-positive">No form flags</li>
        )}
      </ul>
    </li>
  );
}
