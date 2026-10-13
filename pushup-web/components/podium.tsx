import Link from "next/link";
import { Avatar } from "@/components/brodie-avatar";
import { profileHref, StreakChip } from "@/components/leader-row";
import { RankDelta } from "@/components/rank-delta";
import { CrownIcon } from "@/components/ui/icons";
import type { LeaderboardRow } from "@/lib/types";

/** Each step is a mini poster in its own spot color. */
const PLACE = {
  1: { paper: "bg-pink text-ink", tilt: "-rotate-1", pedestal: "h-20 sm:h-28", label: "Champ" },
  2: { paper: "bg-blue text-canvas", tilt: "rotate-1", pedestal: "h-12 sm:h-16", label: "2nd" },
  3: { paper: "bg-yellow text-ink", tilt: "-rotate-[0.75deg]", pedestal: "h-6 sm:h-8", label: "3rd" },
} as const;

function Step({ row }: { row: LeaderboardRow }) {
  const p = PLACE[row.rank as 1 | 2 | 3] ?? PLACE[3];
  const first = row.rank === 1;
  return (
    <li className={`flex min-w-0 flex-col ${first ? "order-2" : row.rank === 2 ? "order-1" : "order-3"}`}>
      <Link
        href={profileHref(row.displayName)}
        className={`group card relative flex min-w-0 flex-col items-center overflow-hidden px-1.5 pt-2 pb-3 text-center transition-transform duration-200 hover:rotate-0 sm:px-3 ${p.paper} ${p.tilt}`}
      >
        <div aria-hidden className="halftone absolute inset-x-0 top-0 h-1/2 opacity-20 [mask-image:linear-gradient(#000,transparent)]" />
        <span aria-hidden className="absolute -top-2 left-1 font-display text-[4.5rem] leading-none opacity-20 sm:text-[7rem]">
          {row.rank}
        </span>
        <span className="relative flex w-full items-center justify-between font-mono text-[0.6rem] font-bold tracking-widest uppercase sm:text-xs">
          <span>No. {row.rank}</span>
          {first ? <CrownIcon className="size-4 sm:size-5" /> : <span>{p.label}</span>}
        </span>
        <span className={`relative ${first ? "[&>svg]:size-24 sm:[&>svg]:size-36" : "[&>svg]:size-18 sm:[&>svg]:size-28"}`}>
          <Avatar level={row.avatarLevel} size={first ? 144 : 112} />
        </span>
        <span className="relative mt-1 block w-full truncate font-display text-lg uppercase sm:text-2xl">{row.displayName}</span>
        <span className={`relative font-display leading-none tabular-nums ${first ? "text-4xl sm:text-6xl" : "text-3xl sm:text-5xl"}`}>
          {row.points.toLocaleString("en-US")}
        </span>
        <span className="relative mt-1.5 flex flex-wrap items-center justify-center gap-1 font-mono text-[0.65rem] font-bold uppercase opacity-80 sm:gap-1.5 sm:text-xs">
          <span className="whitespace-nowrap tabular-nums">{row.validReps.toLocaleString("en-US")} reps</span>
          <StreakChip days={row.streak} />
        </span>
        <span className="relative">
          <RankDelta publicId={row.publicId} />
        </span>
      </Link>
      <div aria-hidden className={`mx-2 mt-2 border-2 border-b-0 border-ink bg-surface-2 halftone [--dot:var(--color-hairline-strong)] ${p.pedestal}`} />
    </li>
  );
}

export function Podium({ rows }: { rows: LeaderboardRow[] }) {
  const top = rows.filter((r) => r.rank >= 1 && r.rank <= 3).slice(0, 3);
  if (top.length === 0) return null;
  return (
    <ol aria-label="Top 3" className="grid grid-cols-3 items-end gap-2 border-b-2 border-ink sm:gap-5">
      {top.map((r) => (
        <Step key={r.publicId} row={r} />
      ))}
    </ol>
  );
}
