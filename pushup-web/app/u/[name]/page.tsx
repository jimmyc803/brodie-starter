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

  return (
    <div className="space-y-8">
      <LiveRefresh />
      <Link href="/" className="text-accent">← Leaderboard</Link>
      <section className="flex flex-wrap items-center gap-6">
        <Avatar level={profile.avatarLevel} size={240} />
        <div>
          <h1 className="font-display break-words text-5xl">{profile.displayName}</h1>
          <p className="mt-2 text-xl text-accent">Level {profile.avatarLevel}</p>
          {nextThreshold !== undefined && <p className="text-ink-2">{nextThreshold - profile.points} points to level {nextLevel}</p>}
        </div>
      </section>
      <dl className="grid grid-cols-2 gap-4 rounded-xl border border-hairline bg-surface p-5 sm:grid-cols-4">
        {[["Total points", profile.points], ["Valid reps", profile.validReps], ["Day streak", profile.streak], ["Rank", profile.rank ? `#${profile.rank}` : "Unranked"]].map(([label, value]) => (
          <div key={label}><dt className="text-sm text-ink-2">{label}</dt><dd className="font-display text-4xl">{value}</dd></div>
        ))}
      </dl>
      <section aria-labelledby="daily-heading">
        <h2 id="daily-heading" className="font-display text-3xl">Points per day</h2>
        <p className="text-sm text-ink-2">Days in Eastern Time. Negative adjustments appear below the line.</p>
        {daily.length === 0 ? <p className="mt-4">No calls yet.</p> : (
          <div className="mt-4 overflow-x-auto">
            <svg role="img" aria-labelledby="daily-title daily-description" viewBox={`0 0 ${width} 300`} style={{ width: "100%", minWidth: width }}>
              <title id="daily-title">Daily points for {profile.displayName}</title>
              <desc id="daily-description">{daily.map((day) => `${day.dateEt}: ${day.points} points`).join("; ")}</desc>
              <line x1="0" x2={width} y1="150" y2="150" stroke="currentColor" opacity="0.4" />
              {daily.map((day, index) => {
                const height = Math.abs(day.points) / maxPoints * 110;
                const x = (index + 0.5) * width / daily.length;
                return (
                  <g key={day.dateEt}>
                    <rect x={x - 20} y={day.points >= 0 ? 150 - height : 150} width="40" height={height} rx="3" fill="#D4FF3A" />
                    <text x={x} y={day.points >= 0 ? 140 - height : 170 + height} fill="currentColor" textAnchor="middle" fontSize="14">{day.points}</text>
                    <text x={x} y="296" fill="currentColor" textAnchor="middle" fontSize="12">{day.dateEt.slice(5)}</text>
                  </g>
                );
              })}
            </svg>
          </div>
        )}
      </section>
      <section>
        <h2 className="font-display text-3xl">Best call</h2>
        {profile.bestCallId ? <Link className="text-accent underline" href={`/r/${encodeURIComponent(profile.bestCallId)}`}>{profile.bestCallPoints} points · View result →</Link> : <p>No scored calls yet.</p>}
      </section>
    </div>
  );
}
