import Link from "next/link";
import { notFound } from "next/navigation";
import { Avatar } from "@/components/brodie-avatar";
import { LiveRefresh } from "@/components/live-refresh";
import { getCompetition, getProfile, getUserDaily } from "@/lib/data";
import { avatarLevelForPoints } from "@/lib/card";

export const dynamic = "force-dynamic";

export default async function ProfilePage({ params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  const [profile, daily, competition] = await Promise.all([getProfile(name), getUserDaily(name), getCompetition()]);
  if (!profile) notFound();
  const maxPoints = Math.max(1, ...daily.map((day) => Math.abs(day.points)));
  const width = Math.max(320, daily.length * 70);
  const thresholds = competition?.avatarLevelThresholds ?? [];
  const nextThreshold = thresholds.find((threshold) => threshold > profile.points);
  const nextLevel = nextThreshold === undefined ? null : avatarLevelForPoints(nextThreshold, thresholds);

  const stats: [string, string][] = [
    ["Total points", profile.points.toLocaleString("en-US")],
    ["Valid reps", profile.validReps.toLocaleString("en-US")],
    ["Day streak", String(profile.streak)],
    ["Rank", profile.rank ? `#${profile.rank}` : "Unranked"],
  ];

  return (
    <div className="space-y-10">
      <LiveRefresh />
      <Link href="/" className="inline-flex min-h-11 items-center font-mono text-sm font-bold uppercase underline decoration-pink decoration-[3px] underline-offset-[6px]">
        ← The standings
      </Link>
      <section className="card relative grid overflow-hidden sm:grid-cols-[18rem_minmax(0,1fr)]">
        <div className="relative grid place-items-center border-b-2 border-ink bg-pink px-6 pt-6 sm:border-r-2 sm:border-b-0">
          <div aria-hidden className="halftone absolute inset-0 opacity-25" />
          <span aria-hidden className="absolute top-2 left-3 font-display text-8xl leading-none text-ink/15">
            {profile.rank ? `#${profile.rank}` : ""}
          </span>
          <span className="relative">
            <Avatar level={profile.avatarLevel} size={240} />
          </span>
        </div>
        <div className="flex flex-col justify-center p-5 sm:p-8">
          <p className="inline-block w-fit border-2 border-ink bg-yellow px-2 py-0.5 font-mono text-xs font-bold tracking-[0.14em] uppercase">
            Level {profile.avatarLevel} Brodie
          </p>
          <h1 className="mt-3 font-display text-hero break-words uppercase">{profile.displayName}</h1>
          {nextThreshold !== undefined && (
            <p className="mt-2 font-mono text-sm font-bold text-ink-2 uppercase">
              {(nextThreshold - profile.points).toLocaleString("en-US")} points to level {nextLevel}
            </p>
          )}
        </div>
      </section>
      <dl className="grid grid-cols-2 border-2 border-ink bg-surface sm:grid-cols-4">
        {stats.map(([label, value], i) => (
          <div key={label} className={`px-4 py-4 sm:px-5 ${i % 2 ? "border-l-2 border-ink" : ""} ${i >= 2 ? "border-t-2 border-ink sm:border-t-0" : ""} ${i === 2 ? "sm:border-l-2" : ""}`}>
            <dt className="eyebrow text-ink">{label}</dt>
            <dd className="mt-1 font-display text-5xl leading-none tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
      <section aria-labelledby="daily-heading" className="card p-5 sm:p-6">
        <h2 id="daily-heading" className="font-display text-4xl uppercase">Points per day</h2>
        <p className="font-mono text-xs text-ink-2 uppercase">Days in Eastern Time. Negative adjustments appear below the line.</p>
        {daily.length === 0 ? <p className="mt-4">No calls yet.</p> : (
          <div className="mt-4 overflow-x-auto">
            <svg role="img" aria-labelledby="daily-title daily-description" viewBox={`0 0 ${width} 300`} style={{ width: "100%", minWidth: width, maxWidth: width * 1.5 }}>
              <title id="daily-title">{`Daily points for ${profile.displayName}`}</title>
              <desc id="daily-description">{daily.map((day) => `${day.dateEt}: ${day.points} points`).join("; ")}</desc>
              <line x1="0" x2={width} y1="150" y2="150" stroke="currentColor" strokeWidth="2" />
              {daily.map((day, index) => {
                const height = Math.abs(day.points) / maxPoints * 110;
                const x = (index + 0.5) * width / daily.length;
                return (
                  <g key={day.dateEt}>
                    <rect x={x - 15} y={(day.points >= 0 ? 150 - height : 150) + 4} width="40" height={height} fill="#2346d8" />
                    <rect x={x - 20} y={day.points >= 0 ? 150 - height : 150} width="40" height={height} fill="#ff3d97" stroke="#16120e" strokeWidth="2" />
                    <text x={x} y={day.points >= 0 ? 140 - height : 170 + height} fill="currentColor" textAnchor="middle" fontSize="16" fontFamily="var(--font-display)">{day.points}</text>
                    <text x={x} y="296" fill="currentColor" textAnchor="middle" fontSize="12" fontFamily="var(--font-mono)">{day.dateEt.slice(5)}</text>
                  </g>
                );
              })}
            </svg>
          </div>
        )}
      </section>
      <section className="flex flex-wrap items-center justify-between gap-4 border-2 border-dashed border-ink px-5 py-4">
        <h2 className="font-display text-3xl uppercase">Best call</h2>
        {profile.bestCallId ? (
          <Link className="press inline-flex min-h-12 items-center border-2 border-ink bg-yellow px-5 font-display text-xl uppercase" href={`/r/${encodeURIComponent(profile.bestCallId)}`}>
            {profile.bestCallPoints} points · View result →
          </Link>
        ) : (
          <p>No scored calls yet.</p>
        )}
      </section>
    </div>
  );
}
