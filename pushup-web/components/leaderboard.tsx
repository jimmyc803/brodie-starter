"use client";

import { useEffect, useState } from "react";
import { Avatar } from "@/components/brodie-avatar";
import { filterByName, ilikePattern, mapLeaderboardRow } from "@/lib/mappers";
import { getBrowserClient } from "@/lib/supabase-browser";
import type { LeaderboardRow } from "@/lib/types";

export function Leaderboard({ rows }: { rows: LeaderboardRow[] }) {
  const [q, setQ] = useState("");
  const [found, setFound] = useState<LeaderboardRow[] | null>(null);
  const needle = q.trim();

  // "Find me" queries the full public leaderboard, independent of the top-100 shown.
  useEffect(() => {
    const sb = getBrowserClient();
    if (!needle || !sb) return;
    let cancelled = false;
    const id = setTimeout(async () => {
      const { data, error } = await sb
        .from("leaderboard_public")
        .select("*")
        .ilike("display_name", ilikePattern(needle))
        .order("rank", { ascending: true })
        .limit(20);
      if (cancelled) return;
      setFound(error || !data ? null : data.map(mapLeaderboardRow));
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(id);
    };
  }, [needle]);

  const shown = needle ? (found ?? filterByName(rows, needle)) : rows;

  return (
    <section aria-label="Leaderboard">
      <label className="block">
        <span className="text-xs font-bold uppercase tracking-widest text-ink-2">Find me</span>
        <input
          type="search"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setFound(null);
          }}
          placeholder="Search your name"
          className="mt-1 w-full rounded-lg border border-hairline bg-surface px-3 py-3 text-base text-ink placeholder:text-ink-2 focus:border-accent focus:outline-none"
        />
      </label>
      {rows.length === 0 && !needle ? (
        <p className="mt-6 text-ink-2">No one on the board yet. Be the first.</p>
      ) : shown.length === 0 ? (
        <p className="mt-6 text-ink-2">No one found with that name.</p>
      ) : (
        <ol className="mt-4 divide-y divide-hairline rounded-xl border border-hairline bg-surface">
          {shown.map((r) => (
            <li key={r.publicId} className="flex items-center gap-3 px-3 py-3">
              <span
                className={`w-10 text-right font-display text-2xl tabular-nums ${r.rank <= 3 ? "text-accent" : "text-ink-2"}`}
              >
                {r.rank}
              </span>
              <Avatar level={r.avatarLevel} size={36} />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold">{r.displayName}</span>
                <span className="text-xs text-ink-2">
                  {r.validReps} valid reps
                  {r.streak > 0 ? ` · ${r.streak}-day streak` : ""}
                  {r.badges.length > 0 ? ` · ${r.badges.join(", ")}` : ""}
                </span>
              </span>
              <span className="text-right">
                <span className="block font-display text-3xl tabular-nums leading-none">{r.points}</span>
                <span className="text-xs uppercase tracking-widest text-ink-2">pts</span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
