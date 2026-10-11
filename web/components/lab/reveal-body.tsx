"use client";

import { useEffect, useState } from "react";

import { SHAPES, VIEWBOX } from "@/lib/body/shapes";
import { BODY_BASE, BODY_STROKE } from "@/lib/body/svg";
import type { MuscleKey } from "@/lib/contract";
import { UNTRAINED, type Fills } from "@/lib/body/variants";

// Animated reveal: every muscle starts dark, then lights up exercise by exercise in workout order.
export function RevealBodies({ fills, order }: { fills: Fills; order: Partial<Record<MuscleKey, number>> }) {
  const [run, setRun] = useState(0);
  const [lit, setLit] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setLit(true), 250);
    return () => clearTimeout(t);
  }, [run]);

  return (
    <div>
      <div className="grid grid-cols-2 gap-2">
        {(["front", "back"] as const).map((side) => (
          <svg key={side} viewBox={`-6 -6 ${VIEWBOX.width + 12} ${VIEWBOX.height + 12}`} className="h-auto w-full">
            {SHAPES[side].map((s, i) => {
              const f = s.muscle ? fills[s.muscle] : undefined;
              const step = s.muscle ? order[s.muscle] : undefined;
              const target = !s.muscle ? BODY_BASE : f?.fill ?? UNTRAINED;
              return (
                <polygon
                  key={i}
                  points={s.points}
                  fill={lit || step === undefined ? target : UNTRAINED}
                  stroke={BODY_STROKE}
                  strokeWidth={0.5}
                  strokeLinejoin="round"
                  style={{ transition: `fill 450ms ease-out ${step === undefined ? 0 : 150 + step * 420}ms` }}
                />
              );
            })}
          </svg>
        ))}
      </div>
      <button
        onClick={() => {
          setLit(false);
          setRun((r) => r + 1);
        }}
        className="mt-3 w-full rounded-full bg-fill py-2 t-callout text-ink hover:bg-white/[.12]"
      >
        Replay reveal
      </button>
    </div>
  );
}
