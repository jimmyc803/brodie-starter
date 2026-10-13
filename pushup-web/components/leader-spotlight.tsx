import Link from "next/link";
import { Avatar } from "@/components/brodie-avatar";
import { profileHref } from "@/components/leader-row";
import { CrownIcon } from "@/components/ui/icons";
import type { LeaderboardRow } from "@/lib/types";

/** Desktop-only hero art: the current #1 as a pasted-up fight poster. Phones get the podium instead. */
export function LeaderSpotlight({ row, final }: { row: LeaderboardRow; final: boolean }) {
  return (
    <Link
      href={profileHref(row.displayName)}
      className="group card relative hidden rotate-[1.5deg] animate-rise overflow-hidden text-center transition-transform duration-300 [animation-delay:100ms] hover:rotate-0 lg:block"
    >
      <p className="flex items-center justify-center gap-2 bg-ink py-2 font-display text-xl tracking-wider text-canvas uppercase">
        <CrownIcon className="size-4 text-yellow" /> {final ? "Champion" : "Current #1"}
      </p>
      <div className="relative bg-pink px-6 pt-4">
        <div aria-hidden className="halftone absolute inset-0 opacity-25" />
        <span aria-hidden className="absolute top-1 left-3 font-display text-[7rem] leading-none text-ink/15">#1</span>
        <span className="relative mx-auto block w-fit">
          <Avatar level={row.avatarLevel} size={196} />
        </span>
      </div>
      <div className="border-t-2 border-ink px-5 pt-3 pb-5">
        <p className="truncate font-display text-4xl uppercase group-hover:text-accent">{row.displayName}</p>
        <p className="mt-1 font-display text-7xl leading-none tabular-nums overprint">
          {row.points.toLocaleString("en-US")}
        </p>
        <p className="mt-3 font-mono text-xs font-bold tracking-wider text-ink-2 uppercase">
          pts · {row.validReps.toLocaleString("en-US")} valid reps · Lv {row.avatarLevel}
        </p>
      </div>
    </Link>
  );
}
