import { RANKS, type SessionRank } from "@/lib/ranks";

// Today's rank on the recap: the tier name in its color (the same color its muscles get on the heat map) and the ladder.
export function RankBadge({ r }: { r: SessionRank }) {
  const { rank, next, skipped } = r;
  const pts = r.score === null ? null : Math.floor(r.score * 100); // floor, so points never reach the next tier before the rank does
  return (
    <section aria-label="Today's rank" className="mt-8 rounded-2xl border border-zinc-800 bg-zinc-900 px-5 py-5">
      <p className="text-xs font-medium uppercase tracking-widest text-zinc-500">Today&apos;s rank</p>
      <div className="mt-2 flex items-baseline justify-between gap-3">
        <p className="text-3xl font-semibold tracking-tight" style={{ color: skipped ? undefined : rank.color }}>
          {rank.name}
        </p>
        {pts !== null ? <p className="text-sm tabular-nums text-zinc-400">{pts} pts</p> : null}
      </div>
      <p className="mt-1 text-sm text-zinc-400">
        {skipped
          ? "No reps counted this session."
          : `Tier ${rank.tier} of ${RANKS.length}${next ? ` · ${Math.max(1, Math.round(next.minScore * 100) - (pts ?? 0))} pts to ${next.name}` : " · top rank"}`}
      </p>

      {/* the ladder: every tier in its color, earned ones solid */}
      <ol className="mt-4 flex gap-1" aria-label="Rank ladder">
        {RANKS.map((x) => {
          const earned = !skipped && x.tier <= rank.tier;
          return (
            <li key={x.key} className="flex-1" title={x.name}>
              <span className="block h-1.5 rounded-full" style={{ background: x.color, opacity: earned ? 1 : 0.2 }} />
            </li>
          );
        })}
      </ol>
      <div className="mt-1.5 flex justify-between text-[11px] text-zinc-500">
        <span>{RANKS[0].name}</span>
        <span>{RANKS[RANKS.length - 1].name}</span>
      </div>
      <p className="mt-3 text-[11px] text-zinc-500">Based on form and completion today, not strength.</p>
    </section>
  );
}
