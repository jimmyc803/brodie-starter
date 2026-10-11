"use client";

import dynamic from "next/dynamic";
import { useState } from "react";

import { REVIEW_CLIPS, clipsForMuscle, type ReviewClip } from "@/lib/rep-review/clips.config";
import type { MuscleKey } from "@/lib/contract";

// The player (and its fonts, canvas engine, MediaPipe loader) only loads when someone opens a review.
export const RepReviewPlayer = dynamic(() => import("@/components/rep-review/rep-review-player").then((m) => m.RepReviewPlayer), {
  ssr: false,
});

export type ReviewContext = { mode: "coach" | "client"; clientName?: string; programHref?: string };

// Client recap: "Review your reps" opens the player on the clips for the muscles this workout trained.
export function ReviewLauncher({ muscles, ...ctx }: ReviewContext & { muscles: MuscleKey[] }) {
  const [open, setOpen] = useState(false);
  const seen = new Set<string>();
  const clips: ReviewClip[] = muscles
    .flatMap((m) => clipsForMuscle(m))
    .filter((c) => (seen.has(c.id) ? false : (seen.add(c.id), true)));
  const list = clips.length ? clips : REVIEW_CLIPS;
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="group flex w-full items-center justify-between gap-3 rounded-2xl border border-[#D4FF00]/25 bg-[#D4FF00]/[0.06] px-4 py-3 text-left transition hover:bg-[#D4FF00]/[0.1]"
      >
        <span>
          <span className="block text-sm font-semibold text-zinc-50">Review your reps</span>
          <span className="block text-xs text-zinc-400">
            {list[0].exercise} · {list[0].setLabel} — every rep scored against your coach&apos;s standard
          </span>
        </span>
        <span className="grid size-9 shrink-0 place-items-center rounded-full bg-[#D4FF00] text-sm text-zinc-950 transition group-hover:scale-105">▶</span>
      </button>
      {open ? <RepReviewPlayer clips={list} {...ctx} onClose={() => setOpen(false)} /> : null}
    </>
  );
}
