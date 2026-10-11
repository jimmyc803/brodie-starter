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

function SetBar({ set }: { set: SetView }) {
  const reached = setReached(set);
  const pct = set.planned_reps ? Math.min(100, (set.completed_reps / set.planned_reps) * 100) : 0;
  const color = COLORS[setColor(set)];
  const flagged = faultyReps(set);

  return (
    <li className="grid grid-cols-[3.25rem_1fr_5rem] items-center gap-3">
      <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Set {set.set_number}</span>
      {reached ? (
        <div className="h-3.5 overflow-hidden rounded-full bg-zinc-800" aria-hidden>
          <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
        </div>
      ) : (
        <div className="h-3.5 rounded-full border border-dashed border-zinc-700" aria-hidden />
      )}
      {reached ? (
        <span className="text-right text-sm leading-tight tabular-nums">
          <span className="font-bold text-white">{set.completed_reps}</span>
          <span className="text-zinc-500">/{set.planned_reps}</span>
          {flagged ? <span className="block text-[11px] text-zinc-500">{flagged} flagged</span> : null}
        </span>
      ) : (
        <span className="text-right text-xs font-medium text-zinc-500">not reached</span>
      )}
    </li>
  );
}

export function ExerciseCard({ exercise }: { exercise: ExerciseView }) {
  const done = completedReps(exercise);
  const planned = plannedReps(exercise);
  const faults = topFaults(exercise.sets.flatMap((s) => s.reps));

  return (
    <article className="rounded-3xl border border-white/5 bg-zinc-900 p-5">
      <header className="flex items-baseline justify-between gap-3">
        <h3 className="text-xl font-bold tracking-tight">{exercise.name}</h3>
        <p className="shrink-0 tabular-nums">
          <span className="text-2xl font-black">{done}</span>
          <span className="text-base font-semibold text-zinc-500">/{planned}</span>
          <span className="ml-1 text-xs text-zinc-500">reps</span>
        </p>
      </header>

      <ul className="mt-4 space-y-3">
        {exercise.sets.map((s) => (
          <SetBar key={s.set_number} set={s} />
        ))}
      </ul>

      <div className="mt-4 border-t border-white/5 pt-4">
        {faults.length ? (
          <>
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-zinc-500">Brodie&apos;s cues</p>
            <ul className="flex flex-wrap gap-2" aria-label="Form flags">
              {faults.map(([cue, n]) => (
                <li
                  key={cue}
                  className="rounded-full border border-yellow-400/20 bg-yellow-400/10 px-3 py-1 text-sm font-medium text-yellow-100"
                >
                  {cue} <span className="tabular-nums text-yellow-200/60">×{n}</span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-sm font-medium text-green-400">No form flags</p>
        )}
      </div>
    </article>
  );
}
