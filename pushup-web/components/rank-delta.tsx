"use client";

import { useEffect, useState } from "react";
import { ArrowDownIcon, ArrowUpIcon } from "@/components/ui/icons";

const SHOW_MS = 12_000;

/**
 * Shows an animated arrow when this row's rank changes between live refreshes.
 * Keyed by publicId upstream, so the component instance follows the athlete as rows reorder.
 */
export function RankDelta({ rank }: { rank: number }) {
  const [prev, setPrev] = useState(rank);
  const [delta, setDelta] = useState(0);
  if (rank !== prev) {
    setPrev(rank);
    setDelta(prev - rank);
  }
  useEffect(() => {
    if (delta === 0) return;
    const id = setTimeout(() => setDelta(0), SHOW_MS);
    return () => clearTimeout(id);
  }, [delta, rank]);

  if (delta === 0) return null;
  const up = delta > 0;
  return (
    <span
      key={`${rank}`}
      className={`inline-flex animate-delta items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[0.6875rem] font-extrabold tabular-nums ${up ? "bg-accent-dim text-accent [--delta-from:0.5rem]" : "bg-bad/15 text-bad [--delta-from:-0.5rem]"}`}
    >
      {up ? <ArrowUpIcon className="size-3" /> : <ArrowDownIcon className="size-3" />}
      {Math.abs(delta)}
      <span className="sr-only">{up ? " places up" : " places down"}</span>
    </span>
  );
}
