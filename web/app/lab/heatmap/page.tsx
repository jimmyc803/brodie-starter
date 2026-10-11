import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { LabBody } from "@/components/lab/lab-body";
import { RevealBodies } from "@/components/lab/reveal-body";
import { SiteHeader } from "@/components/site-header";
import { Stage, Surface } from "@/components/ui/apple";
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
      <div className="flex flex-wrap gap-3 t-caption text-ink-2">
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
    <div className="t-caption text-ink-2">
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
      <div className="mt-6 flex gap-2 t-callout">
        {[
          ["demo", "Sample session"],
          [REAL_WORKOUT, "Jimmy's real workout"],
        ].map(([t, label]) => (
          <Link
            key={t}
            href={`/lab/heatmap?s=${t}`}
            className={`rounded-full px-4 py-1.5 transition-colors ${t === token ? "bg-ink text-canvas" : "bg-fill text-ink hover:bg-white/[.12]"}`}
          >
            {label}
          </Link>
        ))}
      </div>
      <p className="mt-3 t-footnote text-ink-3">
        {view.client.name} · {view.day?.title ?? "Workout"} · {view.exercises.map((e) => e.name).join(", ")}
      </p>

      <div className="mt-6 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {VARIANTS.map((v) => {
          const fills = variantFills(view, v.id);
          const glow = v.id === "neon" || v.id === "thermal";
          return (
            <Surface as="section" key={v.id} className="p-5">
              <h2 className="t-headline">{v.name}</h2>
              <p className="mt-1 min-h-10 t-footnote text-ink-2">{v.what}</p>
              <Stage className="mt-4 grid grid-cols-2 gap-1 p-3">
                <LabBody side="front" fills={fills} glow={glow} id={`${v.id}-f`} className="h-auto w-full" />
                <LabBody side="back" fills={fills} glow={glow} id={`${v.id}-b`} className="h-auto w-full" />
              </Stage>
              <div className="mt-3">
                <Legend kind={v.legend} />
              </div>
            </Surface>
          );
        })}
        <Surface as="section" className="p-5">
          <h2 className="t-headline">F · Animated reveal (C colors)</h2>
          <p className="mt-1 min-h-10 t-footnote text-ink-2">
            Muscles light up exercise by exercise in workout order. For the recap page; the PNG stays still.
          </p>
          <Stage className="mt-4 p-3">
            <RevealBodies fills={variantFills(view, "depth")} order={revealOrder(view)} />
          </Stage>
        </Surface>
      </div>
    </>
  );
}

export default function HeatmapLab({ searchParams }: PageProps<"/lab/heatmap">) {
  return (
    <main className="flex-1 bg-canvas text-ink">
      <SiteHeader context="Design lab" />
      <div className="mx-auto max-w-6xl px-5 pt-10 pb-16 sm:px-6">
        <h1 className="t-display">Heat map options</h1>
        <p className="mt-2 t-body text-ink-2">Same data, five ways to color it. Pick one on your phone.</p>
        <Suspense fallback={<p className="mt-6 t-callout text-ink-3">Loading…</p>}>
          <Lab searchParams={searchParams} />
        </Suspense>
      </div>
    </main>
  );
}
