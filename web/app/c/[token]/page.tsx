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

// Coach dashboard, opened from /c/<coaches.share_token>. ?s=<session share_token> picks the session shown on the right.
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
  const selected = typeof sp.s === "string" ? sp.s : null;
  return <CoachDashboard view={view} token={token} selected={selected} />;
}

function Loading() {
  return (
    <div className="mx-auto w-full max-w-7xl animate-pulse px-4 py-10 sm:px-6">
      <div className="h-6 w-40 rounded-full bg-zinc-900" />
      <div className="mt-4 h-10 w-64 rounded-lg bg-zinc-900" />
      <div className="mt-8 grid gap-6 lg:grid-cols-[380px_1fr]">
        <div className="h-96 rounded-2xl bg-zinc-900" />
        <div className="h-[32rem] rounded-2xl bg-zinc-900" />
      </div>
    </div>
  );
}
