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
    <div className="space-y-6">
      <LiveRefresh />
      <Link href={`/u/${encodeURIComponent(model.displayName)}`} className="text-accent">{model.displayName}’s profile →</Link>
      <h1 className="font-display text-5xl">{model.displayName}’s result</h1>
      {model.void && <p className="rounded-lg border border-hairline p-4 font-bold">This call is void. No points were awarded.</p>}
      <div className="flex items-center justify-center gap-3">
        <div className="text-center"><Avatar level={model.levelBefore} size={140} /><p>Level {model.levelBefore}</p></div>
        <span className="text-4xl text-accent" aria-label="to">→</span>
        <div className="text-center"><Avatar level={model.levelAfter} size={140} /><p>Level {model.levelAfter}</p></div>
      </div>
      <p className="font-display text-6xl text-accent">{model.pointsLabel}</p>
      <p className="text-2xl">{model.validReps} valid · {model.rejectedReps} rejected</p>
      {model.reasons.length > 0 && <section aria-label="Rejection reasons">
        <ul className="space-y-1">{model.reasons.map(({ label, count }) => <li key={label}>{label}: {count}</li>)}</ul>
        <p className="mt-2 text-sm text-ink-2">A rejected rep can have more than one reason.</p>
      </section>}
      <dl className="grid grid-cols-2 gap-4 rounded-xl border border-hairline bg-surface p-5">
        <div><dt className="text-ink-2">Total points</dt><dd className="text-3xl">{model.totalPoints}</dd><dd className="text-sm text-ink-2">{model.pointsBefore} before this call</dd></div>
        <div><dt className="text-ink-2">Rank</dt><dd className="text-3xl">{model.rankLabel}</dd></div>
        <div><dt className="text-ink-2">Current streak</dt><dd>{model.streak === null ? "Unavailable" : `${model.streak} days`}</dd></div>
        <div><dt className="text-ink-2">Next power hour</dt><dd>{model.nextPowerHour}</dd></div>
      </dl>
      <ShareResult title={`${model.displayName}: ${model.pointsLabel}`} />
      <a href={`/r/${encodeURIComponent(callId)}/card`} download="brodie-result.png" className="inline-block text-accent underline">Download result card (PNG)</a>
    </div>
  );
}
