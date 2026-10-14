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
    <span className="inline-flex items-center gap-0.5 border border-ink bg-canvas px-1 py-px font-mono text-[0.65rem] font-bold text-ink">
      <FlameIcon className="size-3 text-live" />
      {days}d<span className="sr-only"> streak</span>
    </span>
  );
}

export function LeaderRow({ row }: { row: LeaderboardRow }) {
  const top10 = row.rank <= 10;
  return (
    <li className="[content-visibility:auto] [contain-intrinsic-size:auto_4.5rem]">
      <Link
        href={profileHref(row.displayName)}
        className="group grid min-h-[4.5rem] grid-cols-[2.75rem_2.75rem_1fr_auto] items-center gap-3 px-3 py-2 transition-colors hover:bg-yellow sm:grid-cols-[3.5rem_3rem_1fr_auto] sm:px-5"
      >
        <span className="flex flex-col items-end">
          <span className={`font-display text-3xl leading-none tabular-nums sm:text-4xl ${top10 ? "text-ink" : "type-outline [-webkit-text-stroke-width:1.5px]"}`}>
            {row.rank}
          </span>
          <RankDelta publicId={row.publicId} />
        </span>
        <span className="grid size-11 place-items-center overflow-hidden rounded-full border-2 border-ink bg-surface-2 sm:size-12">
          <Avatar level={row.avatarLevel} size={44} pose="idle" />
        </span>
        <span className="min-w-0">
          <span className="flex items-baseline gap-2">
            <span className="truncate font-display text-xl uppercase sm:text-2xl">{row.displayName}</span>
            <span aria-hidden className="dot-leader hidden h-2 min-w-6 flex-1 sm:block" />
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-1.5 font-mono text-[0.7rem] text-ink-2 uppercase">
            {/* Valid reps are also the drawing tickets (one each, D-47), so the row names both off the one number. */}
            <span className="tabular-nums" title={`${row.validReps.toLocaleString("en-US")} valid reps = ${row.validReps.toLocaleString("en-US")} drawing tickets`}>
              {row.validReps.toLocaleString("en-US")} reps / tickets
            </span>
            <StreakChip days={row.streak} />
            {row.badges.map((b) => (
              <span key={b} className="hidden border border-ink px-1 py-px text-[0.65rem] font-bold text-ink sm:inline">
                {b}
              </span>
            ))}
          </span>
        </span>
        <span className="text-right">
          <span className="block font-display text-[2rem] leading-none tabular-nums sm:text-[2.5rem]">
            {row.points.toLocaleString("en-US")}
          </span>
          <span className="font-mono text-[0.625rem] font-bold tracking-[0.2em] text-ink-2 uppercase">pts</span>
        </span>
      </Link>
    </li>
  );
}
