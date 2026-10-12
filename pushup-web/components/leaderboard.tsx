"use client";

import { useEffect, useState } from "react";
import { LeaderRow } from "@/components/leader-row";
import { RankDeltaProvider } from "@/components/rank-delta";
import { SearchIcon, XIcon } from "@/components/ui/icons";
import { filterByName, ilikePattern, mapLeaderboardRow } from "@/lib/mappers";
import type { LeaderboardRow } from "@/lib/types";

/**
 * Sticky "find me" + results. When the box is empty it renders `children`
 * (the server-rendered podium and list), so the default board costs no client render work.
 */
export function Leaderboard({ rows, children }: { rows: LeaderboardRow[]; children: React.ReactNode }) {
  const [q, setQ] = useState("");
  const [found, setFound] = useState<LeaderboardRow[] | null>(null);
  const needle = q.trim();

  // "Find me" queries the full public leaderboard, independent of the top-100 shown.
  useEffect(() => {
    if (!needle) return;
    let cancelled = false;
    const id = setTimeout(async () => {
      // Loaded on first search only, keeping supabase-js out of the initial bundle.
      try {
        const { getBrowserClient } = await import("@/lib/supabase-browser");
        const sb = getBrowserClient();
        if (!sb || cancelled) return;
        const { data, error } = await sb
          .from("leaderboard_public")
          .select("*")
          .ilike("display_name", ilikePattern(needle))
          .order("rank", { ascending: true })
          .limit(20);
        if (cancelled) return;
        setFound(error || !data ? null : data.map(mapLeaderboardRow));
      } catch (err) {
        // Network or chunk failure: fall back to filtering the rows already on the page.
        console.error("find me search failed", err);
        if (!cancelled) setFound(null);
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(id);
    };
  }, [needle]);

  const shown = needle ? (found ?? filterByName(rows, needle)) : rows;

  return (
    <section aria-labelledby="board-title" className="space-y-4">
      <div className="sticky top-[3.6rem] z-20 -mx-4 bg-canvas/80 px-4 py-2 backdrop-blur-xl sm:static sm:mx-0 sm:bg-transparent sm:px-0 sm:py-0 sm:backdrop-blur-none">
        <div className="flex items-center gap-3">
          <h2 id="board-title" className="hidden font-display text-3xl font-extrabold uppercase sm:block">
            Leaderboard
          </h2>
          <label className="relative flex-1 sm:ml-auto sm:max-w-sm">
            <span className="sr-only">Find me by display name</span>
            <SearchIcon className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-ink-3" />
            <input
              type="search"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setFound(null);
              }}
              placeholder="Find me: search your name"
              autoComplete="off"
              enterKeyHint="search"
              className="h-12 w-full rounded-full border border-hairline-strong bg-surface pr-12 pl-11 text-base text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none [&::-webkit-search-cancel-button]:hidden"
            />
            {q ? (
              <button
                type="button"
                onClick={() => {
                  setQ("");
                  setFound(null);
                }}
                aria-label="Clear search"
                className="absolute top-1/2 right-1 grid size-11 -translate-y-1/2 place-items-center rounded-full text-ink-2 hover:text-ink"
              >
                <XIcon className="size-4" />
              </button>
            ) : null}
          </label>
        </div>
      </div>

      <RankDeltaProvider rows={rows}>
      {!needle ? (
        children
      ) : shown.length === 0 ? (
        <div className="card p-8 text-center" role="status">
          <p className="font-display text-2xl font-extrabold uppercase">No one named &ldquo;{needle}&rdquo;</p>
          <p className="mt-1 text-sm text-ink-2">Check the spelling, or text JOIN to get on the board.</p>
        </div>
      ) : (
        <>
          <p className="sr-only" role="status">
            {shown.length} {shown.length === 1 ? "match" : "matches"}
          </p>
          <ol className="card divide-y divide-hairline overflow-hidden">
            {shown.map((r) => (
              <LeaderRow key={r.publicId} row={r} />
            ))}
          </ol>
        </>
      )}
      </RankDeltaProvider>
    </section>
  );
}
