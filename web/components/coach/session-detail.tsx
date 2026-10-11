import { PillLink, Stage, Surface } from "@/components/ui/apple";
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

// The selected session, top to bottom: what it was, the numbers, what needs a look, then the full-width heat map with the exercise table below it.
export function SessionDetail({ view, clientName }: { view: SessionView; clientName: string }) {
  const st = sessionStats(view);
  const flagged = flaggedSets(view);
  return (
    <Surface as="section" className="scroll-mt-20 overflow-hidden">
      <span id="session" className="sr-only" />
      <header className="flex flex-wrap items-start justify-between gap-3 p-5 sm:p-6">
        <div className="min-w-0">
          <p className="t-footnote text-ink-2">
            {clientName} · {shortDate(view.session.started_at)}
            {st.minutes ? ` · ${st.minutes} min` : ""}
            {st.endedEarly ? " · ended early" : ""}
          </p>
          <h2 className="t-title mt-0.5 text-ink">{view.day?.title ?? "Workout"}</h2>
        </div>
        <PillLink href={`/r/${encodeURIComponent(view.session.share_token)}`} variant="secondary" className="shrink-0">
          Open client recap <span aria-hidden>→</span>
        </PillLink>
      </header>

      <dl className="grid grid-cols-2 border-y border-hairline sm:grid-cols-4 sm:divide-x sm:divide-hairline">
        <Figure label="Reps counted" value={`${st.completed}`} sub={`/${st.planned}`} />
        <Figure label="Sets" value={`${st.setsDone}`} sub={`/${st.setsPlanned}`} />
        <Figure label="Clean reps" value={pct(st.cleanRate)} />
        <div className="px-5 py-4 sm:px-6">
          <dt className="t-footnote text-ink-2">Muscles</dt>
          <dd className="t-title mt-1 flex items-center gap-3 tabular-nums text-ink">
            <Dot color="green" n={st.green} />
            <Dot color="yellow" n={st.yellow} />
            <Dot color="red" n={st.red} />
          </dd>
        </div>
      </dl>

      <div className="p-5 sm:p-6">
        <NeedsALook flagged={flagged} stats={st} />

        <div className="mt-6 grid gap-8">
          <div className="min-w-0">
            <h3 className="t-headline mb-3 text-ink">Muscle heat map</h3>
            <Stage className="p-5 sm:p-8">
              <Heatmap key={view.session.share_token} details={muscleDetails(view)} order={revealOrder(view)} className="mx-auto max-w-xl" />
            </Stage>
          </div>
          <div className="min-w-0">
            <h3 className="t-headline mb-3 text-ink">Exercises</h3>
            <ExerciseTable exercises={view.exercises} />
            <p className="mt-3 t-caption text-ink-3">
              Each box is one set: reps counted out of planned. Cues are what Brodie said during the sets.
            </p>
          </div>
        </div>
      </div>
    </Surface>
  );
}

function Figure({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="px-5 py-4 sm:px-6">
      <dt className="t-footnote text-ink-2">{label}</dt>
      <dd className="mt-1 tabular-nums">
        <span className="t-title text-ink">{value}</span>
        {sub ? <span className="t-callout text-ink-3">{sub}</span> : null}
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
function NeedsALook({ flagged, stats }: { flagged: ReturnType<typeof flaggedSets>; stats: ReturnType<typeof sessionStats> }) {
  if (flagged.length === 0 && (stats.completed === 0 || stats.endedEarly || stats.completed < stats.planned))
    return (
      <p className="rounded-xl border border-hairline px-4 py-3 t-callout text-ink-2">
        {stats.completed === 0 ? "No reps counted this session." : "Session incomplete. Some planned sets were not completed."}
      </p>
    );
  if (flagged.length === 0)
    return (
      <p className="rounded-xl border border-hairline px-4 py-3 t-callout text-positive">
        Nothing to review. Every set hit its reps with mostly clean form.
      </p>
    );
  return (
    <div className="rounded-xl border border-hairline px-4 py-3">
      <h3 className="t-callout font-semibold text-ink">
        Needs a look <span className="font-normal text-ink-2">· {flagged.length} {flagged.length === 1 ? "set" : "sets"}</span>
      </h3>
      <ul className="mt-2 grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
        {flagged.map((f) => (
          <li key={`${f.exercise}-${f.set_number}`} className="flex items-start gap-2 t-callout">
            <span
              className="mt-1.5 size-2 shrink-0 rounded-full"
              style={{ background: colorOf(f.faulty / Math.max(1, f.completed) >= 0.5 ? "red" : "yellow") }}
            />
            <span className="text-ink-2">
              <span className="font-medium text-ink">{f.exercise}</span> set {f.set_number} · {f.reason}
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
    <div className="rounded-xl border border-hairline">
      <table className="w-full table-fixed t-callout">
        <thead className="text-left t-footnote text-ink-2">
          <tr>
            <th className="px-3 py-2 font-medium sm:px-4">
              Exercise <span className="font-normal text-ink-3">· Brodie&apos;s cues</span>
            </th>
            <th className="w-[38%] px-3 py-2 font-medium">Sets</th>
            <th className="w-16 px-3 py-2 text-right font-medium sm:w-20 sm:px-4">Reps</th>
          </tr>
        </thead>
        <tbody>
          {exercises.map((ex) => {
            const cues = topFaults(ex.sets.flatMap((s) => s.reps));
            return (
              <tr key={ex.exercise_key + ex.name} className="border-t border-hairline align-top">
                <td className="px-3 py-2.5 sm:px-4">
                  <div className="font-medium text-ink">{ex.name}</div>
                  <div className="mt-0.5 t-footnote text-ink-2">
                    {cues.length ? cues.map(([cue, n]) => `${cue} ×${n}`).join(", ") : ex.sets.some(setReached) ? <span className="text-positive">Clean</span> : <span className="text-ink-3">Not reached</span>}
                  </div>
                </td>
                <td className="px-3 py-2.5">
                  <div className="flex flex-wrap gap-1">
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
                          className="min-w-11 rounded-md border border-dashed border-hairline px-1.5 py-0.5 text-center text-xs text-ink-3"
                        >
                          –
                        </span>
                      ),
                    )}
                  </div>
                </td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-ink sm:px-4">
                  {completedReps(ex)}
                  <span className="text-ink-3">/{plannedReps(ex)}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
