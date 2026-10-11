import { Heatmap } from "@/components/heatmap/heatmap";
import { ExerciseCard } from "@/components/recap/exercise-card";
import type { SessionView } from "@/lib/contract";
import { muscleDetails, revealOrder, sessionStats } from "@/lib/recap";

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

function Stat({ value, suffix, label, accent }: { value: string; suffix?: string; label: string; accent?: string }) {
  return (
    <div className="rounded-3xl border border-white/5 bg-zinc-900 px-4 py-4">
      <div className="flex items-baseline tabular-nums">
        <span className="text-4xl font-black tracking-tight" style={accent ? { color: accent } : undefined}>
          {value}
        </span>
        {suffix ? <span className="text-xl font-bold text-zinc-500">{suffix}</span> : null}
      </div>
      <div className="mt-1 text-xs font-semibold uppercase tracking-wider text-zinc-400">{label}</div>
    </div>
  );
}

function SectionTitle({ children, sub }: { children: React.ReactNode; sub?: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-2xl font-extrabold tracking-tight">{children}</h2>
      {sub ? <p className="mt-1 text-sm text-zinc-400">{sub}</p> : null}
    </div>
  );
}

export function RecapView({ view }: { view: SessionView }) {
  const stats = sessionStats(view);
  const date = formatDate(view.session.started_at);
  const subline = [view.day?.title, `Coach ${view.coach.name}`, date].filter(Boolean).join(" · ");
  const clean = stats.cleanRate === null ? null : Math.round(stats.cleanRate * 100);

  return (
    <div className="mx-auto w-full max-w-xl px-4 pb-12 pt-8 sm:px-6 sm:pt-12">
      <header className="relative">
        <div
          aria-hidden
          className="pointer-events-none absolute -top-24 left-1/2 h-64 w-[28rem] -translate-x-1/2 rounded-full bg-green-500/15 blur-3xl"
        />
        <div className="relative">
          <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-semibold tracking-wide text-zinc-200">
            <span className="size-2 rounded-full bg-green-500" />
            Brodie for Coaches
          </span>
          <h1 className="mt-4 text-5xl font-black leading-[1.02] tracking-tight text-balance">
            {view.client.name}&apos;s workout
          </h1>
          <p className="mt-3 text-base font-medium text-zinc-400">{subline}</p>
        </div>
      </header>

      <section aria-label="Session stats" className="mt-8 grid grid-cols-2 gap-3">
        <div className="col-span-2 rounded-3xl border border-green-500/20 bg-gradient-to-br from-green-500/15 to-zinc-900 px-5 py-5">
          <div className="flex items-baseline tabular-nums">
            <span className="text-6xl font-black tracking-tight">{stats.completed}</span>
            <span className="text-3xl font-bold text-zinc-500">/{stats.planned}</span>
          </div>
          <div className="mt-1 text-sm font-semibold uppercase tracking-wider text-green-300">camera-counted reps</div>
        </div>
        <Stat value={String(stats.setsDone)} suffix={`/${stats.setsPlanned}`} label="sets" />
        {clean !== null ? <Stat value={`${clean}`} suffix="%" label="clean reps" /> : null}
        {stats.minutes !== null ? <Stat value={String(stats.minutes)} label="minutes" /> : null}
        <Stat value={String(stats.trained)} label="muscles trained" />
      </section>

      {stats.endedEarly ? (
        <p className="mt-4 rounded-2xl border border-white/5 bg-zinc-900/60 px-4 py-3 text-sm text-zinc-300">
          {stats.completed === 0 ? "Call ended before any reps were counted." : "Call ended before the last set."}
        </p>
      ) : null}

      <section className="mt-12">
        <SectionTitle sub="Estimated coverage from the exercises you did">Muscles worked</SectionTitle>
        <div className="rounded-3xl border border-white/5 bg-zinc-900 p-4 sm:p-6">
          <Heatmap details={muscleDetails(view)} order={revealOrder(view)} />
        </div>
      </section>

      <section className="mt-12">
        <SectionTitle sub="Planned vs. completed, set by set">What you did</SectionTitle>
        <div className="space-y-4">
          {view.exercises.map((ex) => (
            <ExerciseCard key={ex.exercise_key} exercise={ex} />
          ))}
        </div>
      </section>

      <footer className="mt-12 space-y-2 border-t border-white/5 pt-6 text-xs leading-relaxed text-zinc-500">
        <p>
          Estimated coverage based on the exercises completed — not a measurement of muscle activation. Coaching
          feedback, not medical advice.
        </p>
        <p>Reps counted by camera; a few may be missed.</p>
      </footer>
    </div>
  );
}
