import { RANKS, type SessionRank } from "@/lib/ranks";

// Today's rank: the big shareable badge on the recap. Text only for now; Brodie tier art slots in at `art`.
export function RankBadge({ r }: { r: SessionRank }) {
  const { rank, next, skipped } = r;
  const ascended = rank.id === "ascended";
  const pts = r.score === null ? null : Math.floor(r.score * 100); // floor, so points never reach the next tier before the rank does
  return (
    <section
      aria-label="Today's rank"
      className="relative mt-8 overflow-hidden rounded-3xl border bg-zinc-900 px-5 py-6 text-center"
      style={{ borderColor: `${rank.color}55`, boxShadow: ascended ? `0 0 60px ${rank.color}55` : `0 0 40px ${rank.color}22` }}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-16 mx-auto h-40 w-72 rounded-full blur-3xl"
        style={{ background: `${rank.color}${ascended ? "40" : "26"}` }}
      />
      <div className="relative">
        <p className="text-xs font-semibold uppercase tracking-[0.25em] text-zinc-400">Today&apos;s rank</p>
        <p
          className="mt-2 text-4xl font-black uppercase leading-none tracking-tight sm:text-5xl"
          style={{ color: rank.color, textShadow: ascended ? `0 0 24px ${rank.color}` : undefined }}
        >
          {rank.name}
        </p>
        <p className="mt-2 text-sm text-zinc-400">
          {skipped
            ? "No reps counted this session. Every Brodie starts somewhere."
            : `Tier ${rank.tier} of 6${pts !== null ? ` · ${pts} pts` : ""}${next ? ` · ${Math.max(1, Math.round(next.min * 100) - (pts ?? 0))} to ${next.name}` : " · top of the ladder"}`}
        </p>

        {/* the ladder: every tier as a pip, earned ones lit */}
        <ol className="mx-auto mt-4 flex max-w-xs items-center justify-between gap-1" aria-label="Rank ladder">
          {RANKS.slice(1).map((x) => {
            const earned = !skipped && x.tier <= rank.tier;
            const current = !skipped && x.id === rank.id;
            return (
              <li key={x.id} className="flex flex-1 flex-col items-center" title={x.name}>
                <span
                  className="block h-2 w-full rounded-full"
                  style={{ background: earned ? x.color : "#27272a", boxShadow: current ? `0 0 10px ${x.color}` : undefined }}
                />
              </li>
            );
          })}
        </ol>
        <p className="mt-3 text-[11px] text-zinc-500">Based on form and completion today, not strength.</p>
      </div>
    </section>
  );
}
