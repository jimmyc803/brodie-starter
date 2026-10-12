import Link from "next/link";
import { Leaderboard } from "@/components/leaderboard";
import { LiveRefresh } from "@/components/live-refresh";
import { Widgets } from "@/components/widgets";
import { getCompetition, getLeaderboard, getLineStatus, getPowerHour } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function Home() {
  const [rows, line, ph, comp] = await Promise.all([
    getLeaderboard(100),
    getLineStatus(),
    getPowerHour(),
    getCompetition(),
  ]);

  return (
    <div className="space-y-6">
      <LiveRefresh />
      <h1 className="font-display text-5xl uppercase leading-none tracking-wide sm:text-7xl">
        Strict reps. <span className="text-accent">Live board.</span>
      </h1>
      <Widgets
        line={line}
        windowEnd={comp?.windowEnd ?? null}
        frozen={comp?.frozen ?? false}
        powerHour={ph}
      />
      <Link
        href="/join"
        className="inline-block rounded-lg bg-accent px-5 py-3 font-bold uppercase tracking-wide text-on-accent"
      >
        Join the challenge
      </Link>
      <Leaderboard rows={rows} />
    </div>
  );
}
