import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { CoachShell } from "@/components/coach/coach-shell";
import { CoachDashboard, pickSelection } from "@/components/coach/dashboard";
import { getCoachView } from "@/lib/coach-view";
import { sessionClips } from "@/lib/session-video";
import { SAMPLE_COACH_TOKEN } from "@/lib/session-view";

export const metadata: Metadata = {
  title: "Clients · Brodie for Coaches",
  robots: { index: false, follow: false },
};

// Client inbox, /c/<coaches.share_token>/clients. ?c=<client id> picks the client and ?s=<session share_token> the session.
export default function CoachClientsPage({ params, searchParams }: PageProps<"/c/[token]/clients">) {
  return (
    <main className="flex flex-1 flex-col bg-canvas text-ink">
      <Suspense fallback={<div className="min-h-dvh" />}>
        <Clients params={params} searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function Clients({ params, searchParams }: Pick<PageProps<"/c/[token]/clients">, "params" | "searchParams">) {
  await connection(); // private, live data: always render at request time
  const [{ token }, sp] = await Promise.all([params, searchParams]);
  const view = await getCoachView(token);
  if (!view) notFound();
  const pick = (v: string | string[] | undefined) => (typeof v === "string" ? v : null);
  const [selectedClient, selectedSession] = [pick(sp.c), pick(sp.s)];
  const { session, summaries } = pickSelection(view, selectedClient, selectedSession);
  const clips = session ? await sessionClips(session, { demoFallback: token === "demo" || token === SAMPLE_COACH_TOKEN }) : []; // [] when there's no footage: the map just has no videos
  return (
    <CoachShell token={token} coachName={view.coach.name} active="clients" needReview={summaries.filter((s) => s.status === "review").length}>
      <CoachDashboard view={view} token={token} selectedClient={selectedClient} selectedSession={selectedSession} clips={clips} />
    </CoachShell>
  );
}
