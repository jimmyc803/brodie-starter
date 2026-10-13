import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Avatar } from "@/components/brodie-avatar";
import { LiveRefresh } from "@/components/live-refresh";
import { getResultCardModel } from "@/lib/data";
import { ShareResult } from "./share";

export const dynamic = "force-dynamic";
type Props = { params: Promise<{ callId: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { callId } = await params;
  const model = await getResultCardModel(callId);
  if (!model) return { title: "Result not found", robots: { index: false, follow: false } };
  const title = `${model.displayName}: ${model.pointsLabel} | Brodie Push-Ups`;
  const url = `${model.siteUrl}/r/${encodeURIComponent(callId)}`;
  return {
    title,
    description: `${model.validReps} valid reps · ${model.rejectedReps} rejected · ${model.rankLabel}${model.void ? " · Void call" : ""}`,
    openGraph: { title, url, type: "website", images: [{ url: `${url}/card`, width: 1080, height: 1350, type: "image/png", alt: title }] },
    twitter: { card: "summary_large_image", title, images: [`${url}/card`] },
  };
}

export default async function ResultPage({ params }: Props) {
  const { callId } = await params;
  const model = await getResultCardModel(callId);
  if (!model) notFound();
  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <LiveRefresh />
      <Link
        href={`/u/${encodeURIComponent(model.displayName)}`}
        className="inline-flex min-h-11 items-center font-mono text-sm font-bold uppercase underline decoration-pink decoration-[3px] underline-offset-[6px]"
      >
        {model.displayName}’s profile →
      </Link>
      <section className="card relative overflow-hidden">
        <p className="flex items-center justify-between bg-ink px-5 py-2 font-display text-xl tracking-wider text-canvas uppercase">
          <span>Official result</span>
          <span className="font-mono text-xs font-bold tracking-[0.2em] opacity-80">Brodie push-ups</span>
        </p>
        <div className="relative px-5 pt-5 pb-6 sm:px-8">
          <div aria-hidden className="halftone-fade absolute -top-10 -right-10 size-64 [--dot:var(--color-pink)]" />
          <h1 className="relative font-display text-5xl uppercase sm:text-6xl">{model.displayName}</h1>
          {model.void && (
            <p className="relative mt-3 border-2 border-ink bg-yellow p-3 font-bold">This call is void. No points were awarded.</p>
          )}
          <p className="relative mt-2 font-display text-[clamp(4.5rem,18vw,9rem)] leading-[0.85] uppercase overprint">{model.pointsLabel}</p>
          <p className="relative mt-3 font-mono text-sm font-bold uppercase">
            {model.validReps} valid · {model.rejectedReps} rejected
          </p>
          <div className="relative mt-6 flex items-center justify-center gap-2 border-y-2 border-dashed border-ink py-4 sm:gap-6">
            <div className="text-center">
              <Avatar level={model.levelBefore} size={130} />
              <p className="font-mono text-xs font-bold uppercase">Level {model.levelBefore}</p>
            </div>
            <span className="font-display text-6xl text-accent" aria-label="to">→</span>
            <div className="text-center">
              <Avatar level={model.levelAfter} size={130} />
              <p className="font-mono text-xs font-bold uppercase">Level {model.levelAfter}</p>
            </div>
          </div>
          {model.reasons.length > 0 && (
            <section aria-label="Rejection reasons" className="relative mt-5">
              <p className="eyebrow text-ink">Why reps were rejected</p>
              <ul className="mt-2 divide-y divide-dashed divide-hairline-strong">
                {model.reasons.map(({ label, count }) => (
                  <li key={label} className="flex items-baseline gap-2 py-1.5">
                    <span>{label}</span>
                    <span aria-hidden className="dot-leader h-2 flex-1" />
                    <span className="font-display text-xl tabular-nums">{count}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-sm text-ink-2">A rejected rep can have more than one reason.</p>
            </section>
          )}
        </div>
      </section>
      <dl className="grid grid-cols-2 border-2 border-ink bg-surface">
        <div className="p-4 sm:p-5"><dt className="eyebrow text-ink">Total points</dt><dd className="font-display text-4xl leading-none">{model.totalPoints}</dd><dd className="mt-1 text-sm text-ink-2">{model.pointsBefore} before this call</dd></div>
        <div className="border-l-2 border-ink p-4 sm:p-5"><dt className="eyebrow text-ink">Rank</dt><dd className="font-display text-4xl leading-none">{model.rankLabel}</dd></div>
        <div className="border-t-2 border-ink p-4 sm:p-5"><dt className="eyebrow text-ink">Current streak</dt><dd className="mt-1 font-semibold">{model.streak === null ? "Unavailable" : `${model.streak} days`}</dd></div>
        <div className="border-t-2 border-l-2 border-ink p-4 sm:p-5"><dt className="eyebrow text-ink">Next power hour</dt><dd className="mt-1 font-semibold">{model.nextPowerHour}</dd></div>
      </dl>
      <div className="flex flex-wrap items-start gap-5">
        <ShareResult title={`${model.displayName}: ${model.pointsLabel}`} />
        <a
          href={`/r/${encodeURIComponent(callId)}/card`}
          download="brodie-result.png"
          className="inline-flex min-h-12 items-center font-mono text-sm font-bold uppercase underline decoration-pink decoration-[3px] underline-offset-[6px]"
        >
          Download result card (PNG)
        </a>
      </div>
    </div>
  );
}
