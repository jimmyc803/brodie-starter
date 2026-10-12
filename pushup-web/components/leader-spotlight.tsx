import Link from "next/link";
import { Avatar } from "@/components/brodie-avatar";
import { profileHref } from "@/components/leader-row";
import { CrownIcon } from "@/components/ui/icons";
import type { LeaderboardRow } from "@/lib/types";

/** Desktop-only hero art: the current #1 in a trophy-case card. Phones get the podium instead. */
export function LeaderSpotlight({ row, frozen }: { row: LeaderboardRow; frozen: boolean }) {
  return (
    <Link
      href={profileHref(row.displayName)}
      className="group relative hidden animate-rise overflow-hidden rounded-[var(--radius-card)] border border-gold/30 bg-[radial-gradient(22rem_18rem_at_50%_35%,rgb(255_215_94/0.18),transparent_70%)] bg-surface p-6 text-center [animation-delay:100ms] lg:block"
    >
      <span aria-hidden className="pointer-events-none absolute -top-6 -right-2 font-display text-[11rem] leading-none font-extrabold italic text-ink/[0.04]">
        #1
      </span>
      <p className="eyebrow relative inline-flex items-center gap-1.5 text-gold">
        <CrownIcon className="size-4" /> {frozen ? "Champion" : "Current #1"}
      </p>
      <span className="relative mx-auto mt-2 block w-fit">
        <Avatar level={row.avatarLevel} size={208} />
      </span>
      <p className="relative mt-1 truncate font-display text-3xl font-extrabold uppercase group-hover:text-accent">
        {row.displayName}
      </p>
      <p className="relative font-display text-6xl leading-none font-extrabold tabular-nums text-accent">
        {row.points.toLocaleString("en-US")}
        <span className="ml-1.5 text-lg text-ink-2">pts</span>
      </p>
      <p className="relative mt-2 text-sm text-ink-3">
        {row.validReps.toLocaleString("en-US")} valid reps · Level {row.avatarLevel} Brodie
      </p>
    </Link>
  );
}
