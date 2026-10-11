// Derived numbers for the recap page, the coach dashboard and the recap image. Everything here is computed from the
// session view; scores and colors come from muscle_scores as stored by the worker (never recomputed here).
import {
  allMuscles,
  completedReps,
  EXERCISES,
  exercisesForMuscle,
  faultyReps,
  GRAY_LABEL,
  MUSCLES,
  plannedReps,
  setReached,
  topFaults,
  type Color,
  type Coverage,
  type ExerciseKey,
  type MuscleKey,
  type SessionView,
} from "@/lib/contract";

export type MuscleDetail = {
  muscle: MuscleKey;
  label: string;
  color: Color;
  score: number;
  coverage: Coverage;
  note: string; // e.g. "Main muscle · estimated coverage" or "not trained this session"
  exercises: { key: string; name: string; role: "primary" | "secondary"; completed: number; planned: number; flags: [string, number][] }[];
};

export function muscleDetails(view: SessionView): MuscleDetail[] {
  return allMuscles(view).map((m) => {
    const hits = exercisesForMuscle(view, m.muscle);
    return {
      muscle: m.muscle,
      label: MUSCLES[m.muscle].label,
      color: m.color,
      score: m.score,
      coverage: m.coverage,
      note:
        m.color === "gray"
          ? GRAY_LABEL
          : `${m.coverage === "primary" ? "Main" : "Helper"} muscle · estimated coverage`,
      exercises: hits.map(({ exercise, role }) => ({
        key: exercise.exercise_key,
        name: exercise.name,
        role,
        completed: completedReps(exercise),
        planned: plannedReps(exercise),
        flags: topFaults(exercise.sets.flatMap((s) => s.reps)),
      })),
    };
  });
}

export function sessionStats(view: SessionView) {
  const completed = view.exercises.reduce((n, ex) => n + completedReps(ex), 0);
  const planned = view.exercises.reduce((n, ex) => n + plannedReps(ex), 0);
  const allReps = view.exercises.flatMap((ex) => ex.sets.flatMap((s) => s.reps));
  const clean = allReps.filter((r) => r.faults.length === 0).length;
  const setsDone = view.exercises.reduce((n, ex) => n + ex.sets.filter(setReached).length, 0);
  const setsPlanned = view.exercises.reduce((n, ex) => n + ex.sets.length, 0);
  const minutes =
    view.session.ended_at && view.session.started_at
      ? Math.max(1, Math.round((Date.parse(view.session.ended_at) - Date.parse(view.session.started_at)) / 60000))
      : null;
  const colorCount = (c: Color) => view.muscles.filter((m) => m.color === c).length;
  return {
    completed,
    planned,
    completion: planned ? completed / planned : 0,
    cleanRate: allReps.length ? clean / allReps.length : null,
    setsDone,
    setsPlanned,
    minutes,
    green: colorCount("green"),
    yellow: colorCount("yellow"),
    red: colorCount("red"),
    trained: view.muscles.filter((m) => m.color !== "gray").length,
    endedEarly: setsDone < setsPlanned,
  };
}

// Sets worth a coach's look: at least half the reps flagged, or fewer reps than planned in a set that was reached.
export function flaggedSets(view: SessionView) {
  const out: { exercise: string; set_number: number; completed: number; planned: number; faulty: number; reason: string }[] = [];
  for (const ex of view.exercises)
    for (const s of ex.sets) {
      if (!setReached(s)) continue;
      const faulty = faultyReps(s);
      const reasons: string[] = [];
      if (s.completed_reps && faulty / s.completed_reps >= 0.5) reasons.push(`${faulty}/${s.completed_reps} reps flagged`);
      if (s.completed_reps < s.planned_reps) reasons.push(`${s.completed_reps}/${s.planned_reps} reps`);
      if (reasons.length)
        out.push({ exercise: ex.name, set_number: s.set_number, completed: s.completed_reps, planned: s.planned_reps, faulty, reason: reasons.join(" · ") });
    }
  return out;
}

// Order in which muscles light up in the heat map reveal animation: by the first exercise (in workout order) that hit them.
export function revealOrder(view: SessionView): Partial<Record<MuscleKey, number>> {
  const order: Partial<Record<MuscleKey, number>> = {};
  view.exercises.forEach((ex, i) => {
    const info = EXERCISES[ex.exercise_key as ExerciseKey];
    if (!info || !completedReps(ex)) return;
    for (const m of [...info.primary, ...info.secondary]) if (order[m] === undefined) order[m] = i;
  });
  return order;
}
