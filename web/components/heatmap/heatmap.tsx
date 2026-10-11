"use client";

import { useEffect, useId, useState } from "react";

import { BODY_BASE, BODY_STROKE, neonFills, neonLayers, UNTRAINED, type Fills } from "@/lib/body/neon";
import { VIEWBOX, type BodySide } from "@/lib/body/shapes";
import type { Color, MuscleKey } from "@/lib/contract";
import { muscleRank } from "@/lib/ranks";
import type { MuscleDetail } from "@/lib/recap";
import { HeatmapLegend, MuscleSwatch } from "@/components/heatmap/legend";

// Front + back body heat map (the "neon" look from /lab/heatmap). Tap a muscle to see which exercises worked it, its
// score and whether it was a main or helper muscle. With `order`, the map reveals itself when it first shows.
export function Heatmap({
  details,
  order,
  className,
}: {
  details: MuscleDetail[];
  order?: Partial<Record<MuscleKey, number>>;
  className?: string;
}) {
  const [selected, setSelected] = useState<MuscleKey | null>(null);
  // Reveal phases: idle (dark body) -> main (main muscles light up, exercise by exercise) -> helpers (helpers fade in)
  const [phase, setPhase] = useState<"idle" | "main" | "helpers" | "done">(order ? "idle" : "done");
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const fills = neonFills(details);
  const sel = details.find((d) => d.muscle === selected) ?? null;
  const reveal = revealTimeline(details, order);

  useEffect(() => {
    const next = { idle: ["main", 300], main: ["helpers", reveal.helpersAt], helpers: ["done", reveal.helpersFor] } as const;
    if (phase === "done") return;
    const [to, ms] = next[phase];
    const t = setTimeout(() => setPhase(to), ms);
    return () => clearTimeout(t);
  }, [phase, reveal.helpersAt, reveal.helpersFor]);

  return (
    <div className={className}>
      <div className="grid grid-cols-2 gap-2">
        {(["front", "back"] as BodySide[]).map((side) => (
          <figure key={side} className="flex flex-col items-center">
            <Body
              side={side}
              fills={fills}
              id={`${uid}${side}`}
              lit={phase !== "idle"}
              delays={reveal.delays}
              selected={selected}
              onSelect={(m) => setSelected(m === selected ? null : m)}
            />
            <figcaption className="mt-1 text-xs font-medium uppercase tracking-widest text-zinc-500">{side}</figcaption>
          </figure>
        ))}
      </div>
      {order ? <RevealCaption phase={phase} id={uid} /> : null}
      <HeatmapLegend className="mt-4" />
      {order ? (
        <button
          onClick={() => setPhase("idle")}
          className="mx-auto mt-2 block text-xs text-zinc-500 underline-offset-2 hover:text-zinc-300 hover:underline"
        >
          Replay
        </button>
      ) : null}
      <div aria-live="polite" className="mt-4">
        {sel ? <MuscleCard detail={sel} fill={fills[sel.muscle]?.fill ?? UNTRAINED} onClose={() => setSelected(null)} /> : (
          <p className="text-center text-sm text-zinc-500">Tap a muscle to see what worked it</p>
        )}
      </div>
    </div>
  );
}

// When each muscle lights up (ms after the reveal starts): main muscles first, exercise by exercise in workout order,
// then the helper muscles fade in, so the bright-vs-pale difference explains itself.
const MAIN_START = 150;
const MAIN_STEP = 450;
const HELPER_GAP = 350;
const HELPER_STEP = 200;
const FADE_MS = 500;

function revealTimeline(details: MuscleDetail[], order?: Partial<Record<MuscleKey, number>>) {
  const delays: Partial<Record<MuscleKey, number>> = {};
  if (!order) return { delays, helpersAt: 0, helpersFor: 0 };
  const main = details.filter((d) => d.coverage === "primary" && order[d.muscle] !== undefined);
  const helpers = details.filter((d) => d.coverage === "secondary" && order[d.muscle] !== undefined);
  const lastMain = Math.max(-1, ...main.map((d) => order[d.muscle]!));
  const helpersAt = MAIN_START + (lastMain + 1) * MAIN_STEP + HELPER_GAP;
  for (const d of main) delays[d.muscle] = MAIN_START + order[d.muscle]! * MAIN_STEP;
  for (const d of helpers) delays[d.muscle] = helpersAt + order[d.muscle]! * HELPER_STEP;
  const lastHelper = Math.max(0, ...helpers.map((d) => order[d.muscle]!));
  return { delays, helpersAt, helpersFor: helpers.length ? lastHelper * HELPER_STEP + FADE_MS + 900 : 0 };
}

function RevealCaption({ phase, id }: { phase: "idle" | "main" | "helpers" | "done"; id: string }) {
  const show = phase === "main" || phase === "helpers";
  return (
    <div className="mt-3 flex h-6 items-center justify-center gap-4 text-sm font-medium" aria-hidden>
      <span className={`flex items-center gap-1.5 transition-opacity duration-300 ${show ? "opacity-100" : "opacity-0"}`}>
        <MuscleSwatch kind="main" id={`${id}cm`} /> Main muscles
      </span>
      <span className={`flex items-center gap-1.5 text-zinc-400 transition-opacity duration-300 ${phase === "helpers" ? "opacity-100" : "opacity-0"}`}>
        <MuscleSwatch kind="helper" id={`${id}ch`} /> + helpers
      </span>
    </div>
  );
}

const PAD = 6;

function Body({
  side,
  fills,
  id,
  lit,
  delays,
  selected,
  onSelect,
}: {
  side: BodySide;
  fills: Fills;
  id: string;
  lit: boolean;
  delays: Partial<Record<MuscleKey, number>>;
  selected: MuscleKey | null;
  onSelect: (m: MuscleKey) => void;
}) {
  const L = neonLayers(side, fills, id);
  // Reveal: the colored layer fades in per muscle at its delay (main muscles first, then helpers).
  const fade = (m: MuscleKey | null) => {
    const delay = m ? delays[m] : undefined;
    const on = lit || delay === undefined;
    return {
      opacity: on ? 1 : 0,
      transition: lit && delay !== undefined ? `opacity ${FADE_MS}ms ease-out ${delay}ms` : "none",
    };
  };
  return (
    <svg
      viewBox={`${-PAD} ${-PAD} ${VIEWBOX.width + PAD * 2} ${VIEWBOX.height + PAD * 2}`}
      className="h-auto w-full max-w-[230px]"
      role="img"
      aria-label={`${side} view of the body heat map`}
    >
      <defs>
        <filter id={`${id}-halo`} x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="3" />
        </filter>
        {L.gradients.map((g) => (
          <radialGradient key={g.id} id={g.id} cx="50%" cy="45%" r="65%">
            <stop offset="0%" stopColor={g.inner} />
            <stop offset="100%" stopColor={g.outer} />
          </radialGradient>
        ))}
      </defs>
      <g filter={`url(#${id}-halo)`}>
        {L.halo.map((p, i) => (
          <polygon key={i} points={p.points} fill={p.fill} opacity={p.opacity} style={fade(p.muscle)} className="motion-reduce:!transition-none" />
        ))}
      </g>
      {/* untrained base under every muscle, so the reveal starts from a dark body */}
      {L.shapes.map((s, i) => (
        <polygon key={`b${i}`} points={s.points} fill={s.muscle ? UNTRAINED : BODY_BASE} stroke={BODY_STROKE} strokeWidth={0.5} strokeLinejoin="round" />
      ))}
      {L.shapes.map((s, i) => {
        const m = s.muscle;
        if (!m) return null;
        const isSel = m === selected;
        return (
          <polygon
            key={i}
            points={s.points}
            fill={s.fill}
            stroke={isSel ? "#ffffff" : BODY_STROKE}
            strokeWidth={isSel ? 1.4 : 0.5}
            strokeLinejoin="round"
            style={fade(m)}
            className="cursor-pointer hover:brightness-125 motion-reduce:!transition-none"
            onClick={() => onSelect(m)}
          >
            <title>{m}</title>
          </polygon>
        );
      })}
    </svg>
  );
}

const COLOR_WORD: Record<Color, string> = { green: "Solid", yellow: "Room to improve", red: "Needs work", gray: "Not trained" };

function MuscleCard({ detail, fill, onClose }: { detail: MuscleDetail; fill: string; onClose: () => void }) {
  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/80 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="size-3 rounded-full" style={{ background: fill }} />
            <h3 className="text-lg font-semibold">{detail.label}</h3>
          </div>
          <p className="mt-0.5 text-xs text-zinc-400">{detail.note}</p>
          {(() => {
            const r = muscleRank(detail);
            return r ? (
              <span
                className="mt-2 inline-block rounded-full border px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wider"
                style={{ color: r.color, borderColor: `${r.color}66` }}
              >
                {r.name}
              </span>
            ) : null;
          })()}
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
                {e.role === "primary" ? "Main muscle" : "Helper muscle"}
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
