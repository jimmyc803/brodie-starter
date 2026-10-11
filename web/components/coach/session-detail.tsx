import Link from "next/link";

import { Heatmap } from "@/components/heatmap/heatmap";
import {
  completedReps,
  faultyReps,
  plannedReps,
  setReached,
  topFaults,
  type Color,
  type ExerciseView,
  type SessionView,
  type SetView,
} from "@/lib/contract";
import { flaggedSets, muscleDetails, revealOrder, sessionStats } from "@/lib/recap";
import { colorOf, pct, shortDate } from "@/components/coach/format";

// The selected session, top to bottom: what it was, the numbers, what needs a look, then the heat map beside one exercise table.
export function SessionDetail({ view, clientName }: { view: SessionView; clientName: string }) {
  const st = sessionStats(view);
  const flagged = flaggedSets(view);
  return (
    <section id="session" className="scroll-mt-4 rounded-2xl border border-zinc-800 bg-zinc-900">
      <header className="flex flex-wrap items-start justify-between gap-3 p-5 sm:p-6">
        <div className="min-w-0">
          <p className="text-sm text-zinc-500">
            {clientName} · {shortDate(view.session.started_at)}
            {st.minutes ? ` · ${st.minutes} min` : ""}
            {st.endedEarly ? " · ended early" : ""}
          </p>
          <h2 className="mt-0.5 text-2xl font-semibold tracking-tight text-zinc-50">{view.day?.title ?? "Workout"}</h2>
        </div>
        <Link
          href={`/r/${encodeURIComponent(view.session.share_token)}`}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-zinc-50 px-4 py-2 text-sm font-medium text-zinc-950 transition-colors hover:bg-zinc-200"
        >
          Open client recap <span aria-hidden>→</span>
        </Link>
      </header>

      <dl className="grid grid-cols-2 border-y border-zinc-800 sm:grid-cols-4 sm:divide-x sm:divide-zinc-800">
        <Figure label="Reps counted" value={`${st.completed}`} sub={`/${st.planned}`} />
        <Figure label="Sets" value={`${st.setsDone}`} sub={`/${st.setsPlanned}`} />
        <Figure label="Clean reps" value={pct(st.cleanRate)} />
        <div className="px-5 py-4 sm:px-6">
          <dt className="text-xs text-zinc-500">Muscles</dt>
          <dd className="mt-1 flex items-center gap-3 text-xl font-semibold tabular-nums text-zinc-50">
            <Dot color="green" n={st.green} />
            <Dot color="yellow" n={st.yellow} />
            <Dot color="red" n={st.red} />
          </dd>
        </div>
      </dl>

      <div className="p-5 sm:p-6">
        <NeedsALook flagged={flagged} />

        <div className="mt-6 grid gap-8 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <div>
            <h3 className="mb-3 text-sm font-medium text-zinc-400">Muscle heat map</h3>
            <Heatmap key={view.session.share_token} details={muscleDetails(view)} order={revealOrder(view)} className="mx-auto max-w-sm" />
          </div>
          <div className="min-w-0">
            <h3 className="mb-3 text-sm font-medium text-zinc-400">Exercises</h3>
            <ExerciseTable exercises={view.exercises} />
            <p className="mt-3 text-xs text-zinc-500">
              Each box is one set: reps counted out of planned. Cues are what Brodie said during the sets.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

function Figure({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="px-5 py-4 sm:px-6">
      <dt className="text-xs text-zinc-500">{label}</dt>
      <dd className="mt-1 tabular-nums">
        <span className="text-xl font-semibold text-zinc-50">{value}</span>
        {sub ? <span className="text-sm text-zinc-500">{sub}</span> : null}
      </dd>
    </div>
  );
}

function Dot({ color, n }: { color: Color; n: number }) {
  return (
    <span className="flex items-center gap-1.5" title={`${n} ${color}`}>
      <span className="size-2.5 rounded-full" style={{ background: colorOf(color) }} />
      {n}
    </span>
  );
}

// The coach's to-do for this session: sets that came up short or were mostly flagged.
function NeedsALook({ flagged }: { flagged: ReturnType<typeof flaggedSets> }) {
  if (flagged.length === 0)
    return (
      <p className="rounded-xl border border-green-500/20 bg-green-500/5 px-4 py-3 text-sm text-green-300">
        Nothing to review. Every set hit its reps with mostly clean form.
      </p>
    );
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950/40 px-4 py-3">
      <h3 className="text-sm font-medium text-zinc-200">
        Needs a look <span className="text-zinc-500">· {flagged.length} {flagged.length === 1 ? "set" : "sets"}</span>
      </h3>
      <ul className="mt-2 grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
        {flagged.map((f) => (
          <li key={`${f.exercise}-${f.set_number}`} className="flex items-start gap-2 text-sm">
            <span
              className="mt-1.5 size-2 shrink-0 rounded-full"
              style={{ background: colorOf(f.faulty / Math.max(1, f.completed) >= 0.5 ? "red" : "yellow") }}
            />
            <span className="text-zinc-400">
              <span className="font-medium text-zinc-100">{f.exercise}</span> set {f.set_number} · {f.reason}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Share of clean reps in a set -> colour, same rule as the client recap.
function setColor(s: SetView): Color {
  if (!s.completed_reps) return "gray";
  const clean = Math.max(0, s.completed_reps - faultyReps(s)) / s.completed_reps;
  return clean >= 0.8 ? "green" : clean >= 0.5 ? "yellow" : "red";
}

function ExerciseTable({ exercises }: { exercises: ExerciseView[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-zinc-800">
      <table className="w-full text-sm">
        <thead className="bg-zinc-950/40 text-left text-xs text-zinc-500">
          <tr>
            <th className="px-3 py-2 font-medium">Exercise</th>
            <th className="px-3 py-2 font-medium">Sets</th>
            <th className="px-3 py-2 text-right font-medium">Reps</th>
            <th className="px-3 py-2 font-medium">Brodie&apos;s cues</th>
          </tr>
        </thead>
        <tbody>
          {exercises.map((ex) => {
            const cues = topFaults(ex.sets.flatMap((s) => s.reps));
            return (
              <tr key={ex.exercise_key + ex.name} className="border-t border-zinc-800 align-top">
                <td className="whitespace-nowrap px-3 py-2.5 font-medium text-zinc-100">{ex.name}</td>
                <td className="px-3 py-2.5">
                  <div className="flex gap-1">
                    {ex.sets.map((s) =>
                      setReached(s) ? (
                        <span
                          key={s.set_number}
                          title={`Set ${s.set_number}: ${s.completed_reps}/${s.planned_reps}, ${faultyReps(s)} flagged`}
                          className="min-w-11 rounded-md px-1.5 py-0.5 text-center text-xs tabular-nums"
                          style={{ background: `${colorOf(setColor(s))}26`, color: colorOf(setColor(s)) }}
                        >
                          {s.completed_reps}/{s.planned_reps}
                        </span>
                      ) : (
                        <span
                          key={s.set_number}
                          title={`Set ${s.set_number}: not reached`}
                          className="min-w-11 rounded-md border border-dashed border-zinc-700 px-1.5 py-0.5 text-center text-xs text-zinc-600"
                        >
                          –
                        </span>
                      ),
                    )}
                  </div>
                </td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-zinc-300">
                  {completedReps(ex)}
                  <span className="text-zinc-500">/{plannedReps(ex)}</span>
                </td>
                <td className="px-3 py-2.5 text-zinc-400">
                  {cues.length ? cues.map(([cue, n]) => `${cue} ×${n}`).join(", ") : <span className="text-green-400">Clean</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
