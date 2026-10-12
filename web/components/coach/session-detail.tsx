import Link from "next/link";

import { Heatmap } from "@/components/heatmap/heatmap";
import { MuscleBalance } from "@/components/ui-kit/muscle-balance";
import { SetChip } from "@/components/ui-kit/set-chip";
import {
  completedReps,
  plannedReps,
  setReached,
  topFaults,
  type ExerciseClip,
  type ExerciseView,
  type SessionView,
} from "@/lib/contract";
import { formChecked } from "@/lib/quality";
import { flaggedSets, muscleDetails, revealOrder, sessionStats } from "@/lib/recap";
import { pct, shortDate } from "@/components/coach/format";

// The selected session, top to bottom: what it was, the numbers, what needs a look, then the heat map beside one exercise table.
export function SessionDetail({
  view,
  clientName,
  clips,
  programHref,
}: {
  view: SessionView;
  clientName: string;
  clips?: ExerciseClip[];
  programHref?: string; // "Adjust program" in the rep review
}) {
  const st = sessionStats(view);
  const flagged = flaggedSets(view);
  return (
    <section id="session" className="scroll-mt-4 rounded-[14px] border border-line bg-surface">
      <header className="flex flex-wrap items-start justify-between gap-3 p-5 sm:p-6">
        <div className="min-w-0">
          <p className="text-[12.5px] font-medium text-ink-3">
            {clientName} · {shortDate(view.session.started_at)}
            {st.minutes ? ` · ${st.minutes} min` : ""}
            {st.endedEarly ? " · ended early" : ""}
          </p>
          <h2 className="mt-0.5 text-[26px] font-semibold tracking-[-0.025em] text-ink">{view.day?.title ?? "Workout"}</h2>
        </div>
        <Link
          href={`/r/${encodeURIComponent(view.session.share_token)}`}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-[10px] border border-line-strong px-4 py-2 text-sm font-semibold text-ink transition-colors hover:bg-sunken"
        >
          Open client recap <span aria-hidden>→</span>
        </Link>
      </header>

      <dl className="grid grid-cols-2 gap-2 px-5 sm:grid-cols-4 sm:px-6">
        <Figure label="Reps counted" value={`${st.completed}`} sub={`/${st.planned}`} />
        <Figure label="Sets" value={`${st.setsDone}`} sub={`/${st.setsPlanned}`} />
        <Figure label="Clean reps" value={pct(st.cleanRate)} />
        <div className="rounded-[14px] border border-line px-4 py-3">
          <dt className="text-[12.5px] font-medium text-ink-3">Muscles</dt>
          <dd className="mt-3">
            <MuscleBalance view={view} />
          </dd>
        </div>
      </dl>

      <div className="p-5 sm:p-6">
        <NeedsALook flagged={flagged} stats={st} />

        <div className="mt-6 grid gap-8 2xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <div>
            <h3 className="mb-3 text-[12.5px] font-medium text-ink-3">Muscle heat map</h3>
            <div className="rounded-[18px] bg-stage p-4 text-zinc-100">
              <Heatmap
                key={view.session.share_token}
                details={muscleDetails(view)}
                order={revealOrder(view)}
                clips={clips}
                review={{ mode: "coach", clientName, programHref }}
                className="mx-auto max-w-sm"
              />
            </div>
          </div>
          <div className="min-w-0">
            <h3 className="mb-3 text-[12.5px] font-medium text-ink-3">Exercises</h3>
            <ExerciseTable exercises={view.exercises} />
            <p className="mt-3 text-xs text-ink-3">
              Each box is one set: reps done / planned. Hover a box for details. Cues are what Brodie said during the sets.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

function Figure({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-[14px] border border-line px-4 py-3">
      <dt className="text-[12.5px] font-medium text-ink-3">{label}</dt>
      <dd className="mt-2 tabular-nums">
        <span className="text-[34px] font-semibold leading-none tracking-[-0.035em] text-ink">{value}</span>
        {sub ? <span className="text-lg font-semibold text-ink-3">{sub}</span> : null}
      </dd>
    </div>
  );
}

// The coach's to-do for this session: sets that came up short or were mostly flagged.
function NeedsALook({ flagged, stats }: { flagged: ReturnType<typeof flaggedSets>; stats: ReturnType<typeof sessionStats> }) {
  if (flagged.length === 0 && (stats.completed === 0 || stats.endedEarly || stats.completed < stats.planned))
    return (
      <p className="rounded-[14px] border border-line bg-canvas px-4 py-3 text-sm text-ink-2">
        {stats.completed === 0 ? "No reps counted this session." : "Session incomplete. Some planned sets were not completed."}
      </p>
    );
  if (flagged.length === 0)
    return (
      <p className="rounded-[14px] bg-good-soft px-4 py-3 text-sm font-medium text-good">
        Nothing to review. Every set hit its reps with mostly clean form.
      </p>
    );
  return (
    <div className="rounded-[14px] border border-line bg-canvas px-4 py-3">
      <h3 className="text-sm font-semibold text-ink">
        Needs a look <span className="font-normal text-ink-3">· {flagged.length} {flagged.length === 1 ? "set" : "sets"}</span>
      </h3>
      <ul className="mt-2 grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
        {flagged.map((f) => (
          <li key={`${f.exercise}-${f.set_number}`} className="flex items-start gap-2 text-sm">
            <span className={`mt-1.5 size-2 shrink-0 rounded-full ${f.faulty / Math.max(1, f.completed) >= 0.5 ? "bg-bad" : "bg-warn"}`} />
            <span className="text-ink-2">
              <span className="font-semibold text-ink">{f.exercise}</span> set {f.set_number} · {f.reason}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ExerciseTable({ exercises }: { exercises: ExerciseView[] }) {
  return (
    <div className="overflow-x-auto rounded-[14px] border border-line">
      <table className="w-full text-sm">
        <thead className="bg-canvas text-left text-[12.5px] text-ink-3">
          <tr>
            <th className="px-3 py-2 font-medium">Exercise</th>
            <th className="px-3 py-2 font-medium">Sets</th>
            <th className="px-3 py-2 text-right font-medium">Reps</th>
            <th className="min-w-40 px-3 py-2 font-medium">Brodie&apos;s cues</th>
          </tr>
        </thead>
        <tbody>
          {exercises.map((ex) => {
            const cues = topFaults(ex.sets.flatMap((s) => s.reps));
            const reached = ex.sets.some(setReached);
            return (
              <tr key={ex.exercise_key + ex.name} className="border-t border-line align-top">
                <td className="whitespace-nowrap px-3 py-2.5 font-semibold text-ink">{ex.name}</td>
                <td className="px-3 py-2.5">
                  <div className="flex gap-1">
                    {ex.sets.map((s) => (
                      <SetChip key={s.set_number} set={s} exerciseKey={ex.exercise_key} />
                    ))}
                  </div>
                </td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right tabular-nums text-ink">
                  {completedReps(ex)}
                  <span className="text-ink-3">/{plannedReps(ex)}</span>
                </td>
                <td className="px-3 py-2.5 text-ink-2">
                  {!reached ? (
                    <span className="text-ink-3">Not reached</span>
                  ) : !formChecked(ex.exercise_key) ? (
                    <span className="text-ink-3">Reps only · form not checked</span>
                  ) : cues.length ? (
                    cues.map(([cue, n]) => `${cue} ×${n}`).join(", ")
                  ) : (
                    <span className="text-good">Clean</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
