import { SCORE_GRADIENT_CSS, UNTRAINED } from "@/lib/body/neon";

// Legend for the neon heat map: one score bar (the team's red / yellow / green, blended) plus "not trained".
export function HeatmapLegend({ className }: { className?: string }) {
  return (
    <div className={`mx-auto max-w-xs text-xs text-zinc-400 ${className ?? ""}`}>
      <div className="h-2 rounded-full" style={{ background: SCORE_GRADIENT_CSS }} />
      <div className="mt-1 flex justify-between">
        <span>Needs work</span>
        <span>Room to improve</span>
        <span>Solid</span>
      </div>
      <div className="mt-2 flex items-center justify-center gap-3">
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-full" style={{ background: UNTRAINED }} />
          Not trained this session
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-4 rounded-full bg-zinc-500/70" />
          Paler = secondary muscle
        </span>
      </div>
    </div>
  );
}
