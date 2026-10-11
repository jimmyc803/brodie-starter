"use client";

import { useState } from "react";

import { SHAPES, VIEWBOX, type BodySide } from "@/lib/body/shapes";
import { BODY_BASE, BODY_STROKE, fillFor } from "@/lib/body/svg";
import type { Color, MuscleKey } from "@/lib/contract";
import type { MuscleDetail } from "@/lib/recap";
import { HeatmapLegend } from "@/components/heatmap/legend";

// Front + back body heat map. Tap a muscle to see which exercises worked it, its score and coverage.
// Colors come straight from the stored muscle_scores; the drawing shares lib/body/shapes with the recap PNG.
export function Heatmap({ details, className }: { details: MuscleDetail[]; className?: string }) {
  const [selected, setSelected] = useState<MuscleKey | null>(null);
  const colors = Object.fromEntries(details.map((d) => [d.muscle, d.color])) as Record<MuscleKey, Color>;
  const sel = details.find((d) => d.muscle === selected) ?? null;

  return (
    <div className={className}>
      <div className="grid grid-cols-2 gap-2">
        {(["front", "back"] as BodySide[]).map((side) => (
          <figure key={side} className="flex flex-col items-center">
            <Body side={side} colors={colors} selected={selected} onSelect={(m) => setSelected(m === selected ? null : m)} />
            <figcaption className="mt-1 text-xs font-medium uppercase tracking-widest text-zinc-500">{side}</figcaption>
          </figure>
        ))}
      </div>
      <HeatmapLegend className="mt-4" />
      <div aria-live="polite" className="mt-4">
        {sel ? <MuscleCard detail={sel} onClose={() => setSelected(null)} /> : (
          <p className="text-center text-sm text-zinc-500">Tap a muscle to see what worked it</p>
        )}
      </div>
    </div>
  );
}

function Body({
  side,
  colors,
  selected,
  onSelect,
}: {
  side: BodySide;
  colors: Record<MuscleKey, Color>;
  selected: MuscleKey | null;
  onSelect: (m: MuscleKey) => void;
}) {
  return (
    <svg
      viewBox={`0 0 ${VIEWBOX.width} ${VIEWBOX.height}`}
      className="h-auto w-full max-w-[220px]"
      role="img"
      aria-label={`${side} view of the body heat map`}
    >
      {SHAPES[side].map((s, i) => {
        const m = s.muscle;
        const isSel = m !== null && m === selected;
        return (
          <polygon
            key={i}
            points={s.points}
            fill={m ? fillFor(colors[m]) : BODY_BASE}
            stroke={isSel ? "#ffffff" : BODY_STROKE}
            strokeWidth={isSel ? 1.2 : 0.5}
            strokeLinejoin="round"
            className={m ? "cursor-pointer transition-opacity hover:opacity-80" : undefined}
            onClick={m ? () => onSelect(m) : undefined}
          >
            {m ? <title>{m}</title> : null}
          </polygon>
        );
      })}
    </svg>
  );
}

const COLOR_WORD: Record<Color, string> = { green: "Solid", yellow: "Room to improve", red: "Needs work", gray: "Not trained" };

function MuscleCard({ detail, onClose }: { detail: MuscleDetail; onClose: () => void }) {
  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/80 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="size-3 rounded-full" style={{ background: fillFor(detail.color) }} />
            <h3 className="text-lg font-semibold">{detail.label}</h3>
          </div>
          <p className="mt-0.5 text-xs text-zinc-400">{detail.note}</p>
        </div>
        <div className="text-right">
          {detail.color !== "gray" ? (
            <>
              <div className="text-2xl font-bold tabular-nums">{Math.round(detail.score * 100)}</div>
              <div className="text-xs text-zinc-400">{COLOR_WORD[detail.color]}</div>
            </>
          ) : null}
        </div>
      </div>
      {detail.exercises.length ? (
        <ul className="mt-3 space-y-2">
          {detail.exercises.map((e) => (
            <li key={e.name} className="rounded-xl bg-zinc-800/60 px-3 py-2 text-sm">
              <div className="flex justify-between">
                <span className="font-medium">{e.name}</span>
                <span className="tabular-nums text-zinc-300">
                  {e.completed}/{e.planned} reps
                </span>
              </div>
              <div className="mt-0.5 text-xs text-zinc-400">
                {e.role === "primary" ? "Primary" : "Secondary"}
                {e.flags.length ? ` · form flags: ${e.flags.map(([t, n]) => `${t} ×${n}`).join(", ")}` : " · no form flags"}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      <button onClick={onClose} className="mt-3 w-full text-center text-xs text-zinc-500 underline-offset-2 hover:underline">
        Close
      </button>
    </div>
  );
}
