/** Skeleton for the live board while server data streams in. */
export default function Loading() {
  return (
    <div role="status" aria-label="Loading the leaderboard" className="space-y-8 sm:space-y-12">
      <div className="space-y-4">
        <div className="skeleton animate-shimmer h-8 w-40 rounded-full" />
        <div className="skeleton animate-shimmer h-28 w-full max-w-xl sm:h-40" />
        <div className="skeleton animate-shimmer h-6 w-full max-w-md" />
      </div>
      <div className="grid gap-3 lg:grid-cols-12">
        <div className="skeleton animate-shimmer h-44 rounded-[var(--radius-card)] lg:col-span-4" />
        <div className="skeleton animate-shimmer h-44 rounded-[var(--radius-card)] lg:col-span-5" />
        <div className="skeleton animate-shimmer h-44 rounded-[var(--radius-card)] lg:col-span-3" />
      </div>
      <div className="grid grid-cols-3 items-end gap-2 sm:gap-4">
        <div className="skeleton animate-shimmer h-48" />
        <div className="skeleton animate-shimmer h-60" />
        <div className="skeleton animate-shimmer h-40" />
      </div>
      <div className="card divide-y divide-hairline overflow-hidden">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="flex items-center gap-3 px-4 py-3">
            <div className="skeleton animate-shimmer size-11 shrink-0" />
            <div className="flex-1 space-y-2">
              <div className="skeleton animate-shimmer h-4 w-1/3" />
              <div className="skeleton animate-shimmer h-3 w-1/5" />
            </div>
            <div className="skeleton animate-shimmer h-7 w-14" />
          </div>
        ))}
      </div>
      <span className="sr-only">Loading…</span>
    </div>
  );
}
