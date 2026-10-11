import { Heatmap } from "@/components/heatmap/heatmap";
import { ExerciseCard } from "@/components/recap/exercise-card";
import { RankBadge } from "@/components/recap/rank-badge";
import { SectionHeading, SiteHeader } from "@/components/site-header";
import { Stage, Stat, Surface } from "@/components/ui/apple";
import type { ExerciseClip, SessionView } from "@/lib/contract";
import { sessionRank } from "@/lib/ranks";
import { muscleDetails, revealOrder, sessionStats } from "@/lib/recap";

// Stat cells sit centered between the hairline dividers, with room on both sides.
const STAT_CELL = "min-w-0 px-2 text-center sm:px-5";

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

export function RecapView({ view, clips }: { view: SessionView; clips?: ExerciseClip[] }) {
  const stats = sessionStats(view);
  const date = formatDate(view.session.started_at);
  const subline = [view.day?.title, date].filter(Boolean).join(" · ");
  const clean = stats.cleanRate === null ? null : Math.round(stats.cleanRate * 100);

  return (
    <>
      <SiteHeader context={`Coach ${view.coach.name}`} />
      <div className="mx-auto w-full max-w-[692px] px-5 pb-16 pt-8 sm:px-6 sm:pt-12">
        <div>
          <h1 className="t-display text-balance">{view.client.name}&apos;s workout</h1>
          <p className="t-callout mt-2 text-ink-2">{subline}</p>
        </div>

        <Surface className="mt-6">
          <section aria-label="Session stats" className="grid grid-cols-4 divide-x divide-hairline py-4">
            <Stat className={STAT_CELL} value={String(stats.completed)} suffix={`/${stats.planned}`} label="reps" />
            <Stat className={STAT_CELL} value={String(stats.setsDone)} suffix={`/${stats.setsPlanned}`} label="sets" />
            <Stat className={STAT_CELL} value={clean === null ? "–" : String(clean)} suffix={clean === null ? undefined : "%"} label="clean" />
            <Stat className={STAT_CELL} value={stats.minutes === null ? "–" : String(stats.minutes)} label="min" />
          </section>
        </Surface>

        {stats.endedEarly ? (
          <p className="t-callout mt-3 text-ink-2">
            {stats.completed === 0 ? "Call ended before any reps were counted." : "Call ended before the last set."}
          </p>
        ) : null}

        <Surface className="mt-3">
          <RankBadge r={sessionRank(view)} />
        </Surface>

        <section className="mt-12">
          <SectionHeading sub={`${stats.trained} muscles · estimated from the exercises you did`}>Muscles worked</SectionHeading>
          <Stage className="p-4 sm:p-6">
            <Heatmap details={muscleDetails(view)} order={revealOrder(view)} clips={clips} />
          </Stage>
        </section>

        <section className="mt-12">
          <SectionHeading sub="Reps per set and what Brodie cued">What you did</SectionHeading>
          <Surface>
            <ul className="divide-y divide-hairline">
              {view.exercises.map((ex) => (
                <ExerciseCard key={ex.exercise_key} exercise={ex} />
              ))}
            </ul>
          </Surface>
        </section>

        <footer className="t-caption mt-12 space-y-2 border-t border-hairline pt-6 text-ink-3">
          <p>
            Estimated coverage based on the exercises completed — not a measurement of muscle activation. Coaching
            feedback, not medical advice.
          </p>
          <p>Reps counted by camera; a few may be missed.</p>
        </footer>
      </div>
    </>
  );
}
