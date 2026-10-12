import Link from "next/link";
import { Avatar } from "@/components/brodie-avatar";
import { profileHref, StreakChip } from "@/components/leader-row";
import { RankDelta } from "@/components/rank-delta";
import { CrownIcon } from "@/components/ui/icons";
import type { LeaderboardRow } from "@/lib/types";

const PLACE = {
  1: { ring: "ring-gold/70", text: "text-gold", pedestal: "h-28 sm:h-36", glow: "shadow-[0_0_80px_-20px_rgb(255_215_94/0.55)]" },
  2: { ring: "ring-silver/50", text: "text-silver", pedestal: "h-20 sm:h-24", glow: "" },
  3: { ring: "ring-bronze/60", text: "text-bronze", pedestal: "h-14 sm:h-16", glow: "" },
} as const;

function Step({ row }: { row: LeaderboardRow }) {
  const p = PLACE[row.rank as 1 | 2 | 3] ?? PLACE[3];
  const first = row.rank === 1;
  return (
    <li className={`flex min-w-0 flex-col items-center ${first ? "order-2" : row.rank === 2 ? "order-1" : "order-3"}`}>
      <Link href={profileHref(row.displayName)} className="group flex w-full min-w-0 flex-col items-center rounded-2xl px-1 pt-1 text-center">
        {first ? <CrownIcon className="mb-1 size-6 text-gold" /> : null}
        <span className={`relative grid place-items-center rounded-full bg-surface-2 ring-2 ${p.ring} ${p.glow}`}>
          <span className={first ? "[&>svg]:size-22 sm:[&>svg]:size-34" : "[&>svg]:size-16 sm:[&>svg]:size-24"}>
            <Avatar level={row.avatarLevel} size={first ? 136 : 96} />
          </span>
          <span className={`absolute -bottom-2 grid size-7 place-items-center rounded-full bg-canvas font-display text-base font-extrabold ring-2 ${p.ring} ${p.text}`}>
            {row.rank}
          </span>
        </span>
        <span className="mt-4 block w-full truncate font-semibold group-hover:text-accent sm:text-lg">{row.displayName}</span>
        <span className={`font-display font-extrabold tabular-nums leading-none ${first ? "text-4xl text-accent sm:text-5xl" : "text-3xl sm:text-4xl"}`}>
          {row.points.toLocaleString("en-US")}
        </span>
        <span className="mt-1 flex flex-wrap items-center justify-center gap-1 text-xs text-ink-3 sm:gap-1.5">
          <span className="whitespace-nowrap tabular-nums">{row.validReps.toLocaleString("en-US")} reps</span>
          <StreakChip days={row.streak} />
        </span>
        <RankDelta rank={row.rank} />
      </Link>
      <div
        aria-hidden
        className={`mt-3 w-full rounded-t-xl border-x border-t border-hairline bg-gradient-to-b from-surface-3 to-surface ${p.pedestal} relative overflow-hidden`}
      >
        <span className={`absolute inset-x-0 top-1 text-center font-display text-5xl font-extrabold opacity-25 sm:text-6xl ${p.text}`}>
          {row.rank}
        </span>
      </div>
    </li>
  );
}

export function Podium({ rows }: { rows: LeaderboardRow[] }) {
  const top = rows.filter((r) => r.rank >= 1 && r.rank <= 3).slice(0, 3);
  if (top.length === 0) return null;
  return (
    <ol aria-label="Top 3" className="grid grid-cols-3 items-end gap-2 sm:gap-4">
      {top.map((r) => (
        <Step key={r.publicId} row={r} />
      ))}
    </ol>
  );
}
