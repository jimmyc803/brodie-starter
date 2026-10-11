import { RANKS, type SessionRank } from "@/lib/ranks";

// Today's rank on the recap: one compact card, name in the tier colour, the ladder underneath. Tier art slots in later.
export function RankBadge({ r }: { r: SessionRank }) {
  const { rank, next, skipped } = r;
  const pts = r.score === null ? null : Math.floor(r.score * 100); // floor, so points never reach the next tier before the rank does
  return (
    <section aria-label="Today's rank" className="rounded-2xl border border-zinc-800 bg-zinc-900 px-5 py-4">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm text-zinc-400">Today&apos;s rank</p>
        <p className="text-xs tabular-nums text-zinc-500">
          {skipped ? "No reps counted" : `Tier ${rank.tier} of ${RANKS.length}${pts !== null ? ` · ${pts} pts` : ""}`}
        </p>
      </div>
      <p className="mt-1 text-2xl font-bold tracking-tight" style={{ color: skipped ? undefined : rank.color }}>
        {skipped ? "Every Brodie starts somewhere" : rank.name}
      </p>

      {/* the ladder: every tier as a pip, earned ones lit */}
      <ol className="mt-3 flex items-center gap-1" aria-label="Rank ladder">
        {RANKS.map((x) => {
          const earned = !skipped && x.tier <= rank.tier;
          return (
            <li key={x.key} className="flex-1" title={x.name}>
              <span className="block h-1.5 w-full rounded-full" style={{ background: earned ? x.color : "#27272a" }} />
            </li>
          );
        })}
      </ol>
      <p className="mt-2 text-xs text-zinc-500">
        {!skipped && next
          ? `${Math.max(1, Math.round(next.minScore * 100) - (pts ?? 0))} pts to ${next.name}. `
          : !skipped
            ? "Top of the ladder. "
            : ""}
        Based on form and completion, not strength.
      </p>
    </section>
  );
}
