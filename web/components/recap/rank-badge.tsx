import { RANKS, type SessionRank } from "@/lib/ranks";

// Today's rank and ladder use the same discrete colors as the muscle map.
export function RankBadge({ r }: { r: SessionRank }) {
  const { rank, next, skipped } = r;
  const pts = r.score === null ? null : Math.floor(r.score * 100); // floor, so points never reach the next tier before the rank does
  return (
    <section aria-label="Today's rank" className="px-5 py-4">
      <div className="flex items-baseline justify-between gap-3">
        <p className="t-callout text-ink-2">Today&apos;s rank</p>
        <p className="t-footnote tabular-nums text-ink-3">
          {skipped ? "No reps counted" : `Tier ${rank.tier} of ${RANKS.length}${pts !== null ? ` · ${pts} pts` : ""}`}
        </p>
      </div>
      <p className="mt-1 flex items-center gap-2.5 t-title">
        {skipped ? null : <span className="size-3 shrink-0 rounded-full" style={{ background: rank.color }} aria-hidden />}
        <span style={{ color: skipped ? undefined : rank.color }}>{skipped ? "Every Brodie starts somewhere" : rank.name}</span>
      </p>

      {/* Keep every swatch in its exact rank color; outline the current tier. */}
      <ol className="mt-3 flex items-center gap-1" aria-label="Rank ladder">
        {RANKS.map((x) => {
          const current = !skipped && x.tier === rank.tier;
          return (
            <li key={x.key} className="flex-1" title={x.name}>
              <span className={`block h-1.5 w-full rounded-full ${current ? "outline-2 outline-offset-2 outline-ink" : ""}`} style={{ background: x.color }} />
            </li>
          );
        })}
      </ol>
      <p className="mt-2 t-footnote text-ink-2">
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
