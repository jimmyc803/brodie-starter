"use client";

import { useState } from "react";
import { Avatar } from "@/components/brodie-avatar";
import { filterByName } from "@/lib/mappers";
import type { LeaderboardRow } from "@/lib/types";

export function Leaderboard({ rows }: { rows: LeaderboardRow[] }) {
  const [q, setQ] = useState("");
  const shown = filterByName(rows, q);

  return (
    <section aria-label="Leaderboard">
      <label className="block">
        <span className="text-xs font-bold uppercase tracking-widest text-ink-2">Find me</span>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search your name"
          className="mt-1 w-full rounded-lg border border-hairline bg-surface px-3 py-3 text-base text-ink placeholder:text-ink-2 focus:border-accent focus:outline-none"
        />
      </label>
      {rows.length === 0 ? (
        <p className="mt-6 text-ink-2">No one on the board yet. Be the first.</p>
      ) : shown.length === 0 ? (
        <p className="mt-6 text-ink-2">No match in the top {rows.length}.</p>
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
