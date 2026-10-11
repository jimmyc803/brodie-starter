import type { Metadata } from "next";
import { connection } from "next/server";
import { Suspense } from "react";

import { CoachDashboard } from "@/components/coach/dashboard";
import type { CoachView } from "@/lib/coach-view";
import type { SessionView } from "@/lib/contract";
import { sampleSessionView } from "@/lib/session-view";

export const metadata: Metadata = { title: "Coach dashboard lab", robots: { index: false, follow: false } };

const DAY_MS = 24 * 60 * 60 * 1000;

// The sample session re-dated, renamed, and optionally with every fault cleared (an "all clean" workout).
function fake(name: string, daysAgo: number, token: string, clean: boolean): SessionView {
  const v = sampleSessionView();
  const at = new Date(Date.now() - daysAgo * DAY_MS).toISOString();
  return {
    ...v,
    session: { ...v.session, id: token, share_token: token, started_at: at, ended_at: new Date(Date.parse(at) + 8 * 60 * 1000).toISOString() },
    client: { name },
    exercises: clean
      ? v.exercises.map((ex) => ({
          ...ex,
          sets: ex.sets.map((s) => ({ ...s, completed_reps: s.planned_reps, reps: s.reps.map((r) => ({ ...r, faults: [] })) })),
        }))
      : v.exercises,
  };
}

// A made-up roster of six clients, to see the dashboard with more than one client. Not linked from anywhere.
function roster(): CoachView {
  return {
    coach: { name: "Tristan" },
    clients: [
      { id: "ryan", name: "Ryan", next: "Day 2 - Lower body", sessions: [fake("Ryan", 0, "lab-ryan-1", false), fake("Ryan", 2, "lab-ryan-2", true)] },
      { id: "maya", name: "Maya", next: "Day 4 - Upper body", sessions: [fake("Maya", 1, "lab-maya-1", false)] },
      { id: "jordan", name: "Jordan", next: "Day 3 - Full body", sessions: [fake("Jordan", 0, "lab-jordan-1", true), fake("Jordan", 2, "lab-jordan-2", true), fake("Jordan", 4, "lab-jordan-3", true)] },
      { id: "priya", name: "Priya", next: "Day 7 - Lower body", sessions: [fake("Priya", 2, "lab-priya-1", true)] },
      { id: "sam", name: "Sam", next: null, sessions: [fake("Sam", 3, "lab-sam-1", true)] },
      { id: "leo", name: "Leo", next: "Day 3 - Full body", sessions: [fake("Leo", 9, "lab-leo-1", false)] },
    ],
  };
}

export default function CoachLabPage({ searchParams }: PageProps<"/lab/coach">) {
  return (
    <main className="flex-1 bg-canvas text-ink">
      <Suspense>
        <Lab searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function Lab({ searchParams }: { searchParams: PageProps<"/lab/coach">["searchParams"] }) {
  await connection();
  const sp = await searchParams;
  const pick = (v: string | string[] | undefined) => (typeof v === "string" ? v : null);
  return <CoachDashboard view={roster()} token="demo" base="/lab/coach" selectedClient={pick(sp.c)} selectedSession={pick(sp.s)} />;
}
