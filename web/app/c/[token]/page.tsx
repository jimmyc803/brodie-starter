import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { CoachDashboard, pickSelection } from "@/components/coach/dashboard";
import { getCoachView } from "@/lib/coach-view";
import { sessionClips } from "@/lib/session-video";
import { SAMPLE_COACH_TOKEN } from "@/lib/session-view";

export const metadata: Metadata = {
  title: "Coach dashboard · Brodie for Coaches",
  robots: { index: false, follow: false },
};

// Coach dashboard, opened from /c/<coaches.share_token>. ?c=<client id> picks the client and ?s=<session share_token> the session.
// Unknown tokens get a real 404 from web/proxy.ts before rendering; notFound() here is the streamed fallback.
export default function CoachDashboardPage({ params, searchParams }: PageProps<"/c/[token]">) {
  return (
    <main className="flex-1 bg-zinc-950 font-[family-name:var(--font-geist-sans)] text-zinc-100">
      <Suspense fallback={<Loading />}>
        <Dashboard params={params} searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function Dashboard({
  params,
  searchParams,
}: {
  params: Promise<{ token: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  await connection(); // private, live data: always render at request time
  const [{ token }, sp] = await Promise.all([params, searchParams]);
  const view = await getCoachView(token);
  if (!view) notFound();
  const pick = (v: string | string[] | undefined) => (typeof v === "string" ? v : null);
  const [selectedClient, selectedSession] = [pick(sp.c), pick(sp.s)];
  const { session } = pickSelection(view, selectedClient, selectedSession);
  const clips = session ? await sessionClips(session, { demoFallback: token === "demo" || token === SAMPLE_COACH_TOKEN }) : []; // [] when there's no footage: the map just has no videos
  return <CoachDashboard view={view} token={token} selectedClient={selectedClient} selectedSession={selectedSession} clips={clips} />;
}

function Loading() {
  return (
    <div className="mx-auto w-full max-w-7xl animate-pulse px-4 py-10 sm:px-6">
      <div className="h-6 w-40 rounded-full bg-zinc-900" />
      <div className="mt-4 h-10 w-64 rounded-lg bg-zinc-900" />
      <div className="mt-8 grid gap-6 lg:grid-cols-[280px_1fr]">
        <div className="h-96 rounded-2xl bg-zinc-900" />
        <div className="h-[32rem] rounded-2xl bg-zinc-900" />
      </div>
    </div>
  );
}
