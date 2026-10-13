import Image from "next/image";
import Link from "next/link";
import brodie from "@/assets/brodie.png";
import { profileHref } from "@/components/leader-row";
import { CrownIcon } from "@/components/ui/icons";
import type { LeaderboardRow } from "@/lib/types";

/** Brodie the mascot, flexing. Plain image so it can sit anywhere (hero, footer, empty states). */
export function Brodie({ size = 240, className = "", priority = false }: { size?: number; className?: string; priority?: boolean }) {
  return (
    <Image
      src={brodie}
      alt="Brodie, the challenge mascot, flexing"
      width={size}
      height={Math.round((size * brodie.height) / brodie.width)}
      priority={priority}
      className={className}
    />
  );
}

/**
 * Hero art: Brodie on a pink halftone sunburst with a speech bubble. When someone holds #1,
 * a ticket tag pinned to the poster names them, so the hero is never empty.
 */
export function MascotPoster({ leader, final }: { leader: LeaderboardRow | null; final: boolean }) {
  return (
    <div className="relative animate-rise [animation-delay:100ms]">
      <div className="card relative overflow-hidden bg-pink">
        <div aria-hidden className="absolute inset-0 halftone opacity-20" />
        <svg aria-hidden viewBox="0 0 200 200" className="absolute top-1/2 left-1/2 size-[140%] -translate-x-1/2 -translate-y-1/2 animate-spin-slow opacity-25">
          {Array.from({ length: 18 }, (_, i) => (
            <path key={i} d="M100 100 L96 -40 L104 -40 Z" fill="#16120e" transform={`rotate(${i * 20} 100 100)`} />
          ))}
        </svg>
        <div className="relative flex items-end justify-center px-6 pt-16 pb-0 lg:pt-20">
          <Brodie size={300} priority className="relative z-10 h-auto w-56 drop-shadow-[6px_6px_0_rgb(22_18_14/0.9)] sm:w-64 lg:w-72" />
        </div>
        <p className="relative z-20 border-t-2 border-ink bg-ink py-2 text-center font-display text-xl tracking-wider text-canvas uppercase">
          Meet Brodie<span className="text-pink"> ✶ </span>he gets bigger as you rep
        </p>
      </div>

      <p className="absolute top-4 left-4 z-20 max-w-[12rem] -rotate-3 border-2 border-ink bg-canvas px-3 py-2 font-display text-xl leading-tight uppercase shadow-[4px_4px_0_0_var(--color-ink)] after:absolute after:-bottom-[11px] after:left-8 after:size-4 after:rotate-45 after:border-r-2 after:border-b-2 after:border-ink after:bg-canvas">
        {final ? "Good week. Now rest, bro." : "Strict reps only, bro."}
      </p>

      {leader ? (
        <Link
          href={profileHref(leader.displayName)}
          className="press absolute -right-2 bottom-16 z-20 flex rotate-3 items-center gap-2 border-2 border-ink bg-yellow px-3 py-2 sm:-right-4"
        >
          <CrownIcon className="size-5 shrink-0" />
          <span className="min-w-0">
            <span className="block font-mono text-[0.6rem] font-bold tracking-widest uppercase">{final ? "Champion" : "Current #1"}</span>
            <span className="block max-w-[9rem] truncate font-display text-xl leading-none uppercase">{leader.displayName}</span>
          </span>
          <span className="font-display text-3xl leading-none tabular-nums">{leader.points.toLocaleString("en-US")}</span>
        </Link>
      ) : (
        <span className="absolute -right-2 bottom-16 z-20 rotate-3 border-2 border-ink bg-yellow px-3 py-2 font-display text-xl leading-none uppercase shadow-[4px_4px_0_0_var(--color-ink)] sm:-right-4">
          #1 is up for grabs
        </span>
      )}
    </div>
  );
}
