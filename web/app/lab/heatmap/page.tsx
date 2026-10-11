import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { LabBody } from "@/components/lab/lab-body";
import { RevealBodies } from "@/components/lab/reveal-body";
import { COLORS } from "@/lib/contract";
import { revealOrder, SCORE_STOPS, THERMAL_STOPS, UNTRAINED, variantFills, type VariantId } from "@/lib/body/variants";
import { getSessionView } from "@/lib/session-view";

// Design lab: the same session drawn with each heat map coloring option, to pick one on a phone. Not linked anywhere.
export const metadata: Metadata = { title: "Heat map lab", robots: { index: false, follow: false } };

const REAL_WORKOUT = "So2M5YASxwk05o8iPjrs-OM-s_lb8swl"; // Jimmy's test call, 11 Oct (5 squats + 5 push-ups)

const VARIANTS: { id: VariantId; name: string; what: string; legend: "flat" | "score" | "thermal" }[] = [
  { id: "flat", name: "A · Today (flat)", what: "Three set colors from the score thresholds. What the recap shows now.", legend: "flat" },
  { id: "gradient", name: "B · Score gradient", what: "Color slides with the score. Team colors pinned at 0.5 (yellow) and 0.75 (green).", legend: "score" },
  { id: "depth", name: "C · Gradient + depth", what: "Same colors; secondary muscles are paler (worked a little), primary full strength (worked hard).", legend: "score" },
  { id: "neon", name: "D · Neon (C + glow)", what: "C, lit from inside with a soft halo. Solid muscles glow most, so problem areas stay readable.", legend: "score" },
  { id: "thermal", name: "E · Thermal (volume)", what: "Heat-camera ramp by how much each muscle worked (reps × role). Shows volume, NOT form quality.", legend: "thermal" },
];

const gradientCss = (stops: [number, string][]) =>
  `linear-gradient(90deg, ${stops.map(([p, c]) => `${c} ${Math.round(p * 100)}%`).join(", ")})`;

function Legend({ kind }: { kind: "flat" | "score" | "thermal" }) {
  if (kind === "flat")
    return (
      <div className="flex flex-wrap gap-3 text-xs text-zinc-400">
        {(["green", "yellow", "red", "gray"] as const).map((c) => (
          <span key={c} className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-full" style={{ background: COLORS[c] }} />
            {{ green: "Solid", yellow: "Room to improve", red: "Needs work", gray: "Not trained" }[c]}
          </span>
        ))}
      </div>
    );
  const stops = kind === "score" ? SCORE_STOPS : THERMAL_STOPS;
  return (
    <div className="text-xs text-zinc-400">
      <div className="h-2.5 rounded-full" style={{ background: gradientCss(stops) }} />
      <div className="mt-1 flex justify-between">
        <span>{kind === "score" ? "Needs work" : "Light"}</span>
        <span>{kind === "score" ? "Solid" : "Worked hardest"}</span>
      </div>
      <div className="mt-1.5 flex items-center gap-1.5">
        <span className="size-2.5 rounded-full" style={{ background: UNTRAINED }} /> Not trained this session
      </div>
    </div>
  );
}

async function Lab({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const token = typeof sp.s === "string" ? sp.s : "demo";
  const view = await getSessionView(token);
  if (!view) notFound();

  return (
    <>
      <div className="mt-4 flex gap-2 text-sm">
        {[
          ["demo", "Sample session"],
          [REAL_WORKOUT, "Jimmy's real workout"],
        ].map(([t, label]) => (
          <Link
            key={t}
            href={`/lab/heatmap?s=${t}`}
            className={`rounded-full px-3 py-1.5 ${t === token ? "bg-white text-zinc-950" : "border border-zinc-700 text-zinc-300"}`}
          >
            {label}
          </Link>
        ))}
      </div>
      <p className="mt-2 text-xs text-zinc-500">
        {view.client.name} · {view.day?.title ?? "Workout"} · {view.exercises.map((e) => e.name).join(", ")}
      </p>

      <div className="mt-6 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {VARIANTS.map((v) => {
          const fills = variantFills(view, v.id);
          const glow = v.id === "neon" || v.id === "thermal";
          return (
            <section key={v.id} className="rounded-3xl border border-zinc-800 bg-zinc-900 p-4">
              <h2 className="text-lg font-bold">{v.name}</h2>
              <p className="mt-1 min-h-10 text-sm text-zinc-400">{v.what}</p>
              <div className={`mt-3 grid grid-cols-2 gap-1 rounded-2xl p-2 ${glow ? "bg-zinc-950" : ""}`}>
                <LabBody side="front" fills={fills} glow={glow} id={`${v.id}-f`} className="h-auto w-full" />
                <LabBody side="back" fills={fills} glow={glow} id={`${v.id}-b`} className="h-auto w-full" />
              </div>
              <div className="mt-3">
                <Legend kind={v.legend} />
              </div>
            </section>
          );
        })}
        <section className="rounded-3xl border border-zinc-800 bg-zinc-900 p-4">
          <h2 className="text-lg font-bold">F · Animated reveal (C colors)</h2>
          <p className="mt-1 min-h-10 text-sm text-zinc-400">
            Muscles light up exercise by exercise in workout order. For the recap page; the PNG stays still.
          </p>
          <div className="mt-3">
            <RevealBodies fills={variantFills(view, "depth")} order={revealOrder(view)} />
          </div>
        </section>
      </div>
    </>
  );
}

export default function HeatmapLab({ searchParams }: PageProps<"/lab/heatmap">) {
  return (
    <main className="flex-1 bg-zinc-950 px-4 py-8 text-white sm:px-8">
      <div className="mx-auto max-w-6xl">
        <p className="text-xs font-medium uppercase tracking-widest text-green-400">Brodie for Coaches · design lab</p>
        <h1 className="mt-1 text-3xl font-black tracking-tight">Heat map options</h1>
        <p className="mt-1 text-sm text-zinc-400">Same data, five ways to color it. Pick one on your phone.</p>
        <Suspense fallback={<p className="mt-6 text-zinc-500">Loading…</p>}>
          <Lab searchParams={searchParams} />
        </Suspense>
      </div>
    </main>
  );
}
