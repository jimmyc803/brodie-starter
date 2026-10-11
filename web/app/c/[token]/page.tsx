import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { CoachDashboard } from "@/components/coach/dashboard";
import { getCoachView } from "@/lib/coach-view";

export const metadata: Metadata = {
  title: "Coach dashboard · Brodie for Coaches",
  robots: { index: false, follow: false },
};

// Coach dashboard, opened from /c/<coaches.share_token>. ?c=<client id> picks the client and ?s=<session share_token> the session.
// Unknown tokens get a real 404 from web/proxy.ts before rendering; notFound() here is the streamed fallback.
export default function CoachDashboardPage({ params, searchParams }: PageProps<"/c/[token]">) {
  return (
    <main className="flex-1 bg-canvas text-ink">
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
  return <CoachDashboard view={view} token={token} selectedClient={pick(sp.c)} selectedSession={pick(sp.s)} />;
}

function Loading() {
  return (
    <div className="mx-auto w-full max-w-[1120px] animate-pulse px-5 py-10 sm:px-6">
      <div className="h-10 w-64 rounded-xl bg-fill" />
      <div className="mt-8 grid gap-6 lg:grid-cols-[300px_1fr]">
        <div className="h-96 rounded-[18px] bg-fill" />
        <div className="h-[32rem] rounded-[18px] bg-fill" />
      </div>
    </div>
  );
}
