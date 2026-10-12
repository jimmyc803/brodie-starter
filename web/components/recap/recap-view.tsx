import { Heatmap } from "@/components/heatmap/heatmap";
import { ExerciseCard } from "@/components/recap/exercise-card";
import { RankBadge } from "@/components/recap/rank-badge";
import { ReviewLauncher } from "@/components/rep-review/review-launcher";
import { SectionHeading, SiteHeader } from "@/components/site-header";
import { MuscleBalance } from "@/components/ui-kit/muscle-balance";
import type { ExerciseClip, SessionView } from "@/lib/contract";
import { sessionRank } from "@/lib/ranks";
import { muscleDetails, revealOrder, sessionStats } from "@/lib/recap";

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

// One stat card: number, small unit, quiet label underneath.
function Stat({ value, suffix, label }: { value: string; suffix?: string; label: string }) {
  return (
    <div className="rounded-[14px] border border-line bg-surface px-3.5 py-3">
      <div className="tabular-nums">
        <span className="text-[28px] font-semibold leading-none tracking-[-0.035em]">{value}</span>
        {suffix ? <span className="text-base font-semibold text-ink-3">{suffix}</span> : null}
      </div>
      <div className="mt-1.5 text-[12.5px] font-medium text-ink-3">{label}</div>
    </div>
  );
}

export function RecapView({ view, clips }: { view: SessionView; clips?: ExerciseClip[] }) {
  const stats = sessionStats(view);
  const date = formatDate(view.session.started_at);
  const subline = [view.day?.title, date].filter(Boolean).join(" · ");
  const clean = stats.cleanRate === null ? null : Math.round(stats.cleanRate * 100);

  return (
    <div className="mx-auto w-full max-w-xl px-4 pb-12 pt-5 sm:px-6 sm:pt-8">
      <SiteHeader context={`Coach ${view.coach.name}`} />

      <div className="mt-7">
        <p className="text-[12.5px] font-medium text-ink-3">{subline}</p>
        <h1 className="mt-1 text-[34px] font-semibold leading-[1.05] tracking-[-0.025em] text-balance">
          {view.client.name}&apos;s workout
        </h1>
      </div>

      <div className="mt-6 flex items-end gap-3">
        <span className="text-[76px] font-semibold leading-none tracking-[-0.035em] tabular-nums">{stats.completed}</span>
        <span className="pb-2 leading-tight">
          <span className="block text-[12.5px] font-medium text-ink-3">of {stats.planned}</span>
          <span className="block text-[15px] font-semibold">reps counted</span>
        </span>
      </div>

      <section aria-label="Session stats" className="mt-4 grid grid-cols-3 gap-2">
        <Stat value={String(stats.setsDone)} suffix={`/${stats.setsPlanned}`} label="sets" />
        <Stat value={clean === null ? "–" : String(clean)} suffix={clean === null ? undefined : "%"} label="clean reps" />
        <Stat value={stats.minutes === null ? "–" : String(stats.minutes)} label="minutes" />
      </section>

      {stats.endedEarly ? (
        <p className="mt-3 text-sm text-ink-2">
          {stats.completed === 0 ? "Call ended before any reps were counted." : "Call ended before the last set."}
        </p>
      ) : null}

      <div className="mt-3">
        <RankBadge r={sessionRank(view)} />
      </div>

      <div className="mt-3">
        <ReviewLauncher mode="client" clientName={view.client.name} muscles={view.muscles.filter((m) => m.coverage !== "none").map((m) => m.muscle)} />
      </div>

      <section className="mt-10">
        <SectionHeading sub="Estimated from the exercises you did">Muscles worked</SectionHeading>
        <MuscleBalance view={view} />
        <div className="mt-3 rounded-[18px] bg-stage p-4 text-zinc-100 sm:p-6">
          <Heatmap details={muscleDetails(view)} order={revealOrder(view)} clips={clips} review={{ mode: "client", clientName: view.client.name }} />
        </div>
      </section>

      <section className="mt-10">
        <SectionHeading sub="Each box is one set · reps done / planned">What you did</SectionHeading>
        <div className="space-y-2.5">
          {view.exercises.map((ex) => (
            <ExerciseCard key={ex.exercise_key} exercise={ex} />
          ))}
        </div>
      </section>

      <footer className="mt-10 space-y-2 border-t border-line pt-6 text-xs leading-relaxed text-ink-3">
        <p>
          Estimated coverage based on the exercises completed — not a measurement of muscle activation. Coaching
          feedback, not medical advice.
        </p>
        <p>Reps counted by camera; a few may be missed.</p>
      </footer>
    </div>
  );
}
