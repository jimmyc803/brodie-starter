"use client";

import { createContext, use, useEffect, useState } from "react";
import { ArrowDownIcon, ArrowUpIcon } from "@/components/ui/icons";
import { EMPTY_TRACKER, expireDeltas, latestDeltaVersion, trackRanks, type RankDeltaEntry } from "@/lib/rank-tracker";

const SHOW_MS = 12_000;

const RankDeltaContext = createContext<Record<string, RankDeltaEntry>>({});

/**
 * Tracks rank changes for the whole board by publicId across live refreshes. Lives above both the
 * podium and the list, so an athlete moving between them keeps their arrow.
 */
export function RankDeltaProvider({
  rows,
  children,
}: {
  rows: readonly { publicId: string; rank: number }[];
  children: React.ReactNode;
}) {
  const [tracked, setTracked] = useState(() => ({ rows, state: trackRanks(EMPTY_TRACKER, rows) }));
  if (tracked.rows !== rows) {
    setTracked({ rows, state: trackRanks(tracked.state, rows) });
  }
  const { state } = tracked;
  const fresh = latestDeltaVersion(state);

  useEffect(() => {
    if (fresh == null) return;
    const id = setTimeout(() => {
      setTracked((t) => ({ ...t, state: expireDeltas(t.state, fresh) }));
    }, SHOW_MS);
    return () => clearTimeout(id);
  }, [fresh]);

  return <RankDeltaContext value={state.deltas}>{children}</RankDeltaContext>;
}

/** Animated arrow for this athlete's latest rank change, if any. */
export function RankDelta({ publicId }: { publicId: string }) {
  const entry = use(RankDeltaContext)[publicId];
  if (!entry || entry.delta === 0) return null;
  const up = entry.delta > 0;
  return (
    <span
      key={entry.version}
      className={`inline-flex animate-delta items-center gap-0.5 border border-ink px-1 py-px font-mono text-[0.65rem] font-bold tabular-nums ${up ? "bg-blue text-canvas [--delta-from:0.5rem]" : "bg-bad text-canvas [--delta-from:-0.5rem]"}`}
    >
      {up ? <ArrowUpIcon className="size-3" /> : <ArrowDownIcon className="size-3" />}
      {Math.abs(entry.delta)}
      <span className="sr-only">{up ? " places up" : " places down"}</span>
    </span>
  );
}
