import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { CoachShell, coachLinks } from "@/components/coach/coach-shell";
import { GettingStarted, WelcomeBanner, type Step } from "@/components/coach/getting-started";
import { Overview } from "@/components/coach/overview";
import { coachOverview } from "@/lib/coach-overview";
import { getCoachView } from "@/lib/coach-view";
import { readOnlyCoachToken } from "@/lib/programWorkflow";

export const metadata: Metadata = {
  title: "Coach dashboard · Brodie for Coaches",
  robots: { index: false, follow: false },
};

// Coach home, opened from /c/<coaches.share_token>: the week at a glance. Clients live at /clients, programs at /program.
// Unknown tokens get a real 404 from web/proxy.ts before rendering; notFound() here is the streamed fallback.
export default function CoachHomePage({ params, searchParams }: PageProps<"/c/[token]">) {
  return (
    <main className="flex flex-1 flex-col bg-zinc-950 font-[family-name:var(--font-geist-sans)] text-zinc-100">
      <Suspense fallback={<div className="min-h-dvh" />}>
        <Home params={params} searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function Home({ params, searchParams }: Pick<PageProps<"/c/[token]">, "params" | "searchParams">) {
  await connection(); // private, live data: always render at request time
  const [{ token }, sp] = await Promise.all([params, searchParams]);
  // Older links pointed ?c= / ?s= at this page: send them to the client inbox.
  if (typeof sp.c === "string" || typeof sp.s === "string") {
    const q = new URLSearchParams();
    if (typeof sp.c === "string") q.set("c", sp.c);
    if (typeof sp.s === "string") q.set("s", sp.s);
    redirect(`/c/${encodeURIComponent(token)}/clients?${q}`);
  }
  const view = await getCoachView(token);
  if (!view) notFound();
  const o = coachOverview(view);
  const links = coachLinks(token);
  const canEdit = token !== "demo" && !readOnlyCoachToken(token);
  const steps: Step[] = [
    { done: view.programs > 0, title: "Upload a program", sub: "The PDF you already give clients", href: links.programs, cta: "Upload" },
    { done: view.clients.length > 0, title: "Add a client", sub: "Just their name", href: links.clients, cta: "Add client" },
    { done: view.clients.some((c) => c.next), title: "Assign their first day", sub: "What they train on their next call", href: `${links.programs}#assign`, cta: "Assign" },
    { done: view.clients.some((c) => c.sessions.length > 0), title: "Send their workout link", sub: "They tap Start workout; you see the recap", href: links.clients, cta: "Get link" },
  ];
  const showSteps = canEdit && steps.some((s) => !s.done);
  return (
    <CoachShell token={token} coachName={view.coach.name} active="overview" needReview={o.needReview}>
      {canEdit && sp.welcome === "1" ? (
        <div className="mb-6">
          <WelcomeBanner coachName={view.coach.name} />
        </div>
      ) : null}
      {showSteps ? (
        <div className="mb-6">
          <GettingStarted steps={steps} />
        </div>
      ) : null}
      <Overview o={o} token={token} coachName={view.coach.name} />
    </CoachShell>
  );
}
