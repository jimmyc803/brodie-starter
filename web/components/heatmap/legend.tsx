"use client";

import { useId } from "react";

import { neonFill, SCORE_GRADIENT_CSS, UNTRAINED } from "@/lib/body/neon";
import { mixOklch } from "@/lib/color";

// A tiny muscle shape drawn exactly like the heat map: a bright, glowing main muscle or a pale helper muscle.
export function MuscleSwatch({ kind, id, className }: { kind: "main" | "helper"; id?: string; className?: string }) {
  const auto = useId().replace(/[^a-zA-Z0-9]/g, "");
  const gid = `sw${id ?? auto}`;
  const f = neonFill({ muscle: "quads", score: 0.85, color: "green", coverage: kind === "main" ? "primary" : "secondary" });
  const lit = f.glow > 0.3;
  return (
    <svg viewBox="-3 -3 22 14" className={`h-3.5 w-6 shrink-0 overflow-visible ${className ?? ""}`} aria-hidden>
      <defs>
        <radialGradient id={gid} cx="50%" cy="45%" r="65%">
          <stop offset="0%" stopColor={lit ? mixOklch(f.fill, "#ffffff", 0.35 * f.glow) : f.fill} />
          <stop offset="100%" stopColor={lit ? mixOklch(f.fill, "#000000", 0.25) : f.fill} />
        </radialGradient>
        <filter id={`${gid}h`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="1.6" />
        </filter>
      </defs>
      {lit ? <rect x="0" y="0" width="16" height="8" rx="4" fill={f.fill} opacity={0.8 * f.glow} filter={`url(#${gid}h)`} /> : null}
      <rect x="0" y="0" width="16" height="8" rx="4" fill={`url(#${gid})`} stroke="#18181b" strokeWidth="0.6" />
    </svg>
  );
}

// Legend for the neon heat map: the score bar (the team's red / yellow / green, blended), what bright vs pale means,
// and "not trained".
export function HeatmapLegend({ className }: { className?: string }) {
  return (
    <div className={`mx-auto max-w-xs text-xs text-zinc-400 ${className ?? ""}`}>
      <div className="h-2 rounded-full" style={{ background: SCORE_GRADIENT_CSS }} />
      <div className="mt-1 flex justify-between">
        <span>Needs work</span>
        <span>Room to improve</span>
        <span>Solid</span>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5">
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
