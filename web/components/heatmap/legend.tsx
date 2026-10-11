"use client";

import { useId } from "react";

import { neonFill, UNTRAINED } from "@/lib/body/neon";
import { RANKS } from "@/lib/ranks";

// A tiny muscle shape drawn exactly like the heat map: a main muscle with a stronger halo or a helper with a subtle halo.
export function MuscleSwatch({ kind, id, className }: { kind: "main" | "helper"; id?: string; className?: string }) {
  const auto = useId().replace(/[^a-zA-Z0-9]/g, "");
  const gid = `sw${id ?? auto}`;
  const f = neonFill({ muscle: "quads", score: 0.85, color: "green", coverage: kind === "main" ? "primary" : "secondary" });
  return (
    <svg viewBox="-3 -3 22 14" className={`h-3.5 w-6 shrink-0 overflow-visible ${className ?? ""}`} aria-hidden>
      <defs>
        <filter id={`${gid}h`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="1.6" />
        </filter>
      </defs>
      {f.glow > 0 ? <rect x="0" y="0" width="16" height="8" rx="4" fill={f.fill} opacity={0.8 * f.glow} filter={`url(#${gid}h)`} /> : null}
      <rect x="0" y="0" width="16" height="8" rx="4" fill={f.fill} stroke="#18181b" strokeWidth="0.6" />
    </svg>
  );
}

// Legend for the neon heat map: the rank ladder (each tier's color is exactly the color its muscles are painted), what
// strong vs subtle halo means, and "not trained".
export function HeatmapLegend({ className }: { className?: string }) {
  return (
    <div className={`mx-auto max-w-sm text-xs text-on-stage-2 ${className ?? ""}`}>
      <ol className="grid grid-cols-2 gap-x-4 gap-y-1.5" aria-label="Ranks, lowest to highest">
        {RANKS.map((r) => (
          <li key={r.key} className="flex items-center gap-1.5">
            <span className="size-2.5 shrink-0 rounded-sm" style={{ background: r.color }} />
            <span>{r.name}</span>
          </li>
        ))}
      </ol>
      <div className="mt-3 flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 border-t border-hairline pt-3">
        <span className="flex items-center gap-1.5">
          <MuscleSwatch kind="main" /> Main muscle
        </span>
        <span className="flex items-center gap-1.5">
          <MuscleSwatch kind="helper" /> Helper muscle
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-full" style={{ background: UNTRAINED }} /> Not trained
        </span>
      </div>
    </div>
  );
}
