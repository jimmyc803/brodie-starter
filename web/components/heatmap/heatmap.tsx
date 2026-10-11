"use client";

import { useEffect, useId, useState } from "react";

import { BODY_BASE, BODY_STROKE, neonFills, neonLayers, UNTRAINED, type Fills } from "@/lib/body/neon";
import { VIEWBOX, type BodySide } from "@/lib/body/shapes";
import type { ExerciseClip, MuscleKey } from "@/lib/contract";
import type { MuscleDetail } from "@/lib/recap";
import { rankForScore } from "@/lib/ranks";
import { HeatmapLegend, MuscleSwatch } from "@/components/heatmap/legend";
import { ClipPlayer } from "@/components/heatmap/clip-player";

// Front + back body heat map (the "neon" look from /lab/heatmap). Tap a muscle to see which exercises worked it, its
// score and whether it was a main or helper muscle. With `order`, the map reveals itself when it first shows. With
// `clips`, each exercise in the muscle card gets a Watch button that plays that part of the workout recording.
export function Heatmap({
  details,
  order,
  clips,
  className,
}: {
  details: MuscleDetail[];
  order?: Partial<Record<MuscleKey, number>>;
  clips?: ExerciseClip[];
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
            <figcaption className="mt-1 text-xs font-medium capitalize text-on-stage-2">{side}</figcaption>
          </figure>
        ))}
      </div>
      {order ? <RevealCaption phase={phase} id={uid} /> : null}
      <HeatmapLegend className="mt-4" />
      {order ? (
        <button
          onClick={() => setPhase("idle")}
          className="mx-auto mt-2 block rounded-full px-3 py-1 text-xs font-medium text-on-stage-2 hover:bg-fill hover:text-on-stage"
        >
          Replay
        </button>
      ) : null}
      <div aria-live="polite" className="mt-4">
        {sel ? <MuscleCard detail={sel} fill={fills[sel.muscle]?.fill ?? UNTRAINED} clips={clips} onClose={() => setSelected(null)} /> : (
          <p className="text-center text-sm text-on-stage-2">
            {clips?.length ? "Tap a muscle to see what worked it — and watch the reps" : "Tap a muscle to see what worked it"}
          </p>
        )}
      </div>
    </div>
  );
}

// When each muscle lights up (ms after the reveal starts): main muscles first, exercise by exercise in workout order,
// then helper muscles fade in with a subtler halo while retaining their rank color.
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
  const show = phase !== "idle"; // stays on screen once the reveal has run
  return (
    <div className="mt-3 flex h-6 items-center justify-center gap-4 text-sm font-medium text-on-stage" aria-hidden>
      <span className={`flex items-center gap-1.5 transition-opacity duration-300 ${show ? "opacity-100" : "opacity-0"}`}>
        <MuscleSwatch kind="main" id={`${id}cm`} /> Main muscles
      </span>
      <span className={`flex items-center gap-1.5 text-on-stage-2 transition-opacity duration-300 ${phase === "helpers" || phase === "done" ? "opacity-100" : "opacity-0"}`}>
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
            className="cursor-pointer hover:stroke-white motion-reduce:!transition-none"
            onClick={() => onSelect(m)}
          >
            <title>{m}</title>
          </polygon>
        );
      })}
    </svg>
  );
}

function MuscleCard({
  detail,
  fill,
  clips,
  onClose,
}: {
  detail: MuscleDetail;
  fill: string;
  clips?: ExerciseClip[];
  onClose: () => void;
}) {
  const [playing, setPlaying] = useState<{ clip: ExerciseClip; ex: MuscleDetail["exercises"][number] } | null>(null);
  const rank = detail.color !== "gray" ? rankForScore(detail.score) : null;
  return (
    <div className="rounded-[18px] bg-fill p-4 text-on-stage">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="size-3 rounded-full" style={{ background: fill }} />
            <h3 className="text-lg font-semibold">{detail.label}</h3>
          </div>
          <p className="mt-0.5 text-xs text-on-stage-2">{detail.note}</p>
        </div>
        {rank ? (
          <div className="text-right">
            <div className="text-2xl font-bold tabular-nums">{Math.round(detail.score * 100)}</div>
            <div className="text-xs font-semibold" style={{ color: rank.color }}>
              {rank.name}
            </div>
          </div>
        ) : (
          <div className="text-right text-xs text-on-stage-2">Not trained</div>
        )}
      </div>
      {detail.exercises.length ? (
        <ul className="mt-3 space-y-2">
          {detail.exercises.map((e) => {
            const clip = clips?.find((c) => c.exercise_key === e.key);
            return (
              <li key={e.name} className="rounded-xl bg-fill px-3 py-2 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{e.name}</span>
                  <span className="flex items-center gap-2">
                    <span className="tabular-nums text-on-stage-2">
                      {e.completed}/{e.planned} reps
                    </span>
                    {clip ? (
                      <button
                        onClick={() => setPlaying({ clip, ex: e })}
                        className="inline-flex items-center gap-1 rounded-full bg-accent-fill px-3 py-1 text-xs font-semibold text-white hover:bg-accent-fill-hover"
                      >
                        Watch
                      </button>
                    ) : null}
                  </span>
                </div>
                <div className="mt-0.5 text-xs text-on-stage-2">
                  {e.role === "primary" ? "Main muscle" : "Helper muscle"}
                  {e.flags.length ? ` · form flags: ${e.flags.map(([t, n]) => `${t} ×${n}`).join(", ")}` : " · no form flags"}
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
      {playing ? (
        <ClipPlayer
          clip={playing.clip}
          title={`${playing.ex.name} · ${detail.label}`}
          subtitle={`${playing.ex.role === "primary" ? "Main muscle" : "Helper muscle"} · ${playing.ex.completed}/${playing.ex.planned} reps`}
          onClose={() => setPlaying(null)}
        />
      ) : null}
      <button onClick={onClose} className="mt-3 w-full rounded-full py-1.5 text-center text-xs font-medium text-on-stage-2 hover:bg-fill">
        Close
      </button>
    </div>
  );
}
