import Link from "next/link";

import { Heatmap } from "@/components/heatmap/heatmap";
import { faultyReps, setReached, topFaults, type ExerciseView, type SessionView } from "@/lib/contract";
import { muscleDetails, sessionStats } from "@/lib/recap";
import { colorOf, pct, shortDate } from "@/components/coach/format";

// The selected session: heat map, per-exercise set table with Brodie's form cues, and a link to the client recap.
export function SessionDetail({ view, clientName }: { view: SessionView; clientName: string }) {
  const st = sessionStats(view);
  return (
    <section id="session" className="scroll-mt-4 rounded-2xl border border-zinc-800 bg-zinc-900 p-4 sm:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-widest text-zinc-500">
            {clientName} · {shortDate(view.session.started_at)}
            {st.minutes ? ` · ${st.minutes} min` : ""}
          </p>
          <h2 className="mt-1 text-xl font-semibold text-zinc-50 sm:text-2xl">{view.day?.title ?? "Workout"}</h2>
          <p className="mt-1 text-sm text-zinc-400">
            {st.completed}/{st.planned} camera-counted reps · {pct(st.cleanRate)} clean · {st.setsDone}/{st.setsPlanned} sets
            {st.endedEarly ? " · ended early" : ""}
          </p>
        </div>
        <Link
          href={`/r/${encodeURIComponent(view.session.share_token)}`}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-zinc-50 px-4 py-2 text-sm font-medium text-zinc-950 transition-colors hover:bg-zinc-200"
        >
          Open client recap <span aria-hidden>→</span>
        </Link>
      </header>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div>
          <h3 className="mb-3 text-xs font-medium uppercase tracking-widest text-zinc-500">Muscle heat map</h3>
          <Heatmap key={view.session.share_token} details={muscleDetails(view)} className="mx-auto max-w-md" />
        </div>
        <div>
          <h3 className="mb-3 text-xs font-medium uppercase tracking-widest text-zinc-500">Exercises</h3>
          <div className="space-y-3">
            {view.exercises.map((ex) => (
              <ExerciseTable key={ex.exercise_key + ex.name} ex={ex} />
            ))}
          </div>
          <p className="mt-3 text-xs text-zinc-500">
            Reps are camera-counted by Brodie. Form flags are what Brodie cued during the set.
          </p>
        </div>
      </div>
    </section>
  );
}

function ExerciseTable({ ex }: { ex: ExerciseView }) {
  const done = ex.sets.reduce((n, s) => n + s.completed_reps, 0);
  const planned = ex.sets.reduce((n, s) => n + s.planned_reps, 0);
  return (
    <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/40">
      <div className="flex items-baseline justify-between gap-2 border-b border-zinc-800 px-3 py-2">
        <p className="font-medium text-zinc-100">{ex.name}</p>
        <p className="text-xs tabular-nums text-zinc-400">
          {done}/{planned} reps
        </p>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-zinc-500">
            <th className="w-12 px-3 py-1.5 font-medium">Set</th>
            <th className="w-16 px-1 py-1.5 font-medium">Reps</th>
            <th className="w-16 px-1 py-1.5 font-medium">Flagged</th>
            <th className="px-3 py-1.5 font-medium">Form flags</th>
          </tr>
        </thead>
        <tbody>
          {ex.sets.map((s) => {
            const reached = setReached(s);
            const faulty = faultyReps(s);
            const flags = topFaults(s.reps);
            const short = s.completed_reps < s.planned_reps;
            const flagColor = faulty === 0 ? undefined : colorOf(faulty / Math.max(1, s.completed_reps) >= 0.5 ? "red" : "yellow");
            return (
              <tr key={s.set_number} className="border-t border-zinc-800/70 align-top">
                <td className="px-3 py-2 tabular-nums text-zinc-400">{s.set_number}</td>
                {reached ? (
                  <>
                    <td className={`px-1 py-2 tabular-nums ${short ? "text-amber-300" : "text-zinc-100"}`}>
                      {s.completed_reps}/{s.planned_reps}
                    </td>
                    <td className="px-1 py-2 tabular-nums" style={{ color: flagColor ?? "#71717a" }}>
                      {faulty}
                    </td>
                    <td className="px-3 py-2 text-zinc-300">
                      {flags.length ? flags.map(([cue, n]) => `${cue} ×${n}`).join(", ") : <span className="text-zinc-600">Clean</span>}
                    </td>
                  </>
                ) : (
                  <td colSpan={3} className="px-1 py-2 italic text-zinc-500">
                    not reached ({s.planned_reps} planned)
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
