import Link from "next/link";
import { Avatar } from "@/components/brodie-avatar";
import { RankDelta } from "@/components/rank-delta";
import { FlameIcon } from "@/components/ui/icons";
import type { LeaderboardRow } from "@/lib/types";

export function profileHref(displayName: string): string {
  return `/u/${encodeURIComponent(displayName)}`;
}

export function StreakChip({ days }: { days: number }) {
  if (days <= 0) return null;
  return (
    <span className="inline-flex items-center gap-0.5 rounded-full bg-[rgb(255_140_60/0.14)] px-1.5 py-0.5 text-[0.6875rem] font-bold text-[#ffb27a]">
      <FlameIcon className="size-3" />
      {days}d<span className="sr-only"> streak</span>
    </span>
  );
}

export function LeaderRow({ row }: { row: LeaderboardRow }) {
  return (
    <li className="[content-visibility:auto] [contain-intrinsic-size:auto_4.25rem]">
      <Link
        href={profileHref(row.displayName)}
        className="group grid min-h-[4.25rem] grid-cols-[2.5rem_2.75rem_1fr_auto] items-center gap-3 px-3 py-2 transition-colors hover:bg-surface-2 sm:grid-cols-[3rem_3rem_1fr_auto] sm:px-5"
      >
        <span className="flex flex-col items-end">
          <span className={`font-display text-2xl font-bold tabular-nums leading-none ${row.rank <= 10 ? "text-ink" : "text-ink-3"}`}>
            {row.rank}
          </span>
          <RankDelta rank={row.rank} />
        </span>
        <span className="grid size-11 place-items-center overflow-hidden rounded-xl bg-surface-2 ring-1 ring-hairline sm:size-12">
          <Avatar level={row.avatarLevel} size={44} pose="idle" />
        </span>
        <span className="min-w-0">
          <span className="block truncate font-semibold group-hover:text-accent">{row.displayName}</span>
          <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-ink-3">
            <span className="tabular-nums">{row.validReps.toLocaleString("en-US")} reps</span>
            <StreakChip days={row.streak} />
            {row.badges.map((b) => (
              <span key={b} className="hidden rounded-full border border-hairline px-1.5 py-0.5 text-[0.6875rem] font-semibold text-ink-2 sm:inline">
                {b}
              </span>
            ))}
          </span>
        </span>
        <span className="text-right">
          <span className="block font-display text-[1.75rem] font-extrabold tabular-nums leading-none">
            {row.points.toLocaleString("en-US")}
          </span>
          <span className="text-[0.625rem] font-bold uppercase tracking-[0.2em] text-ink-3">pts</span>
        </span>
      </Link>
    </li>
  );
}
