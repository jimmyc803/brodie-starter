import { Heatmap } from "@/components/heatmap/heatmap";
import { ExerciseCard } from "@/components/recap/exercise-card";
import { RankBadge } from "@/components/recap/rank-badge";
import { SectionHeading, SiteHeader } from "@/components/site-header";
import type { SessionView } from "@/lib/contract";
import { sessionRank } from "@/lib/ranks";
import { muscleDetails, revealOrder, sessionStats } from "@/lib/recap";

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

// One figure in the stats strip: big number, small unit, quiet label.
function Stat({ value, suffix, label }: { value: string; suffix?: string; label: string }) {
  return (
    <div className="px-3 py-3 text-center sm:px-4">
      <div className="tabular-nums">
        <span className="text-2xl font-bold tracking-tight text-zinc-50">{value}</span>
        {suffix ? <span className="text-sm font-medium text-zinc-500">{suffix}</span> : null}
      </div>
      <div className="mt-0.5 text-xs text-zinc-500">{label}</div>
    </div>
  );
}

export function RecapView({ view }: { view: SessionView }) {
  const stats = sessionStats(view);
  const date = formatDate(view.session.started_at);
  const subline = [view.day?.title, date].filter(Boolean).join(" · ");
  const clean = stats.cleanRate === null ? null : Math.round(stats.cleanRate * 100);

  return (
    <div className="mx-auto w-full max-w-xl px-4 pb-12 pt-5 sm:px-6 sm:pt-8">
      <SiteHeader context={`Coach ${view.coach.name}`} />

      <div className="mt-8">
        <h1 className="text-3xl font-bold tracking-tight text-balance text-zinc-50 sm:text-4xl">
          {view.client.name}&apos;s workout
        </h1>
        <p className="mt-1.5 text-sm text-zinc-400">{subline}</p>
      </div>

      <section
        aria-label="Session stats"
        className="mt-6 grid grid-cols-4 divide-x divide-zinc-800 rounded-2xl border border-zinc-800 bg-zinc-900"
      >
        <Stat value={String(stats.completed)} suffix={`/${stats.planned}`} label="reps" />
        <Stat value={String(stats.setsDone)} suffix={`/${stats.setsPlanned}`} label="sets" />
        <Stat value={clean === null ? "–" : String(clean)} suffix={clean === null ? undefined : "%"} label="clean" />
        <Stat value={stats.minutes === null ? "–" : String(stats.minutes)} label="min" />
      </section>

      {stats.endedEarly ? (
        <p className="mt-3 text-sm text-zinc-400">
          {stats.completed === 0 ? "Call ended before any reps were counted." : "Call ended before the last set."}
        </p>
      ) : null}

      <div className="mt-3">
        <RankBadge r={sessionRank(view)} />
      </div>

      <section className="mt-10">
        <SectionHeading sub={`${stats.trained} muscles · estimated from the exercises you did`}>Muscles worked</SectionHeading>
        <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-4 sm:p-6">
          <Heatmap details={muscleDetails(view)} order={revealOrder(view)} />
        </div>
      </section>

      <section className="mt-10">
        <SectionHeading sub="Reps per set and what Brodie cued">What you did</SectionHeading>
        <div className="space-y-2.5">
          {view.exercises.map((ex) => (
            <ExerciseCard key={ex.exercise_key} exercise={ex} />
          ))}
        </div>
      </section>

      <footer className="mt-10 space-y-2 border-t border-zinc-800 pt-6 text-xs leading-relaxed text-zinc-500">
        <p>
          Estimated coverage based on the exercises completed — not a measurement of muscle activation. Coaching
          feedback, not medical advice.
        </p>
        <p>Reps counted by camera; a few may be missed.</p>
      </footer>
    </div>
  );
}
