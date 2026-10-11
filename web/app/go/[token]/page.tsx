import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { CallLauncher } from "@/components/call/call-launcher";
import { SiteHeader } from "@/components/site-header";
import { getClientHome } from "@/lib/client-view";

export const metadata: Metadata = {
  title: "Your workout · Brodie",
  description: "Train with Brodie: your coach's program, counted rep by rep.",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

// A client's personal link, /go/<clients.share_token>: today's workout, a button that starts the call, and past recaps.
export default function ClientHomePage({ params }: PageProps<"/go/[token]">) {
  return (
    <main className="flex flex-1 flex-col bg-zinc-950 text-zinc-100">
      <Suspense fallback={<div className="min-h-dvh" />}>
        <ClientHome params={params} />
      </Suspense>
    </main>
  );
}

async function ClientHome({ params }: Pick<PageProps<"/go/[token]">, "params">) {
  await connection(); // private, live data
  const { token } = await params;
  const c = await getClientHome(token);
  if (!c) notFound();
  const first = c.name.split(" ")[0];
  return (
    <div className="mx-auto w-full max-w-md px-4 pb-12 pt-5">
      <SiteHeader context={`Coach ${c.coachName}`} />
      <h1 className="mt-8 text-3xl font-bold tracking-tight text-zinc-50">Hi {first} 👋</h1>
      <p className="mt-1 text-zinc-400">Ready when you are. Brodie counts every rep and tells you how to fix your form.</p>

      <section className="mt-6 rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
        <p className="text-sm text-zinc-500">Today&apos;s workout</p>
        <p className="mt-0.5 text-xl font-semibold text-zinc-50">{c.next ?? "Not assigned yet"}</p>
        <p className="mt-1 text-sm text-zinc-400">
          {c.next ? `From Coach ${c.coachName}.` : `Coach ${c.coachName} hasn't picked your next workout yet. Check back soon.`}
        </p>
        {c.next ? (
          <div className="mt-5">
            <CallLauncher token={token} firstName={first} />
          </div>
        ) : null}
      </section>

      <ul className="mt-4 space-y-1.5 text-sm text-zinc-400">
        <li>• Use Safari or Chrome and allow the camera when asked.</li>
        <li>• Prop the phone up, step back until your whole body is in view.</li>
        <li>• Your camera is only used live to count reps. Video is never recorded.</li>
      </ul>

      <section className="mt-8">
        <h2 className="text-base font-semibold text-zinc-100">Your recaps</h2>
        {c.recaps.length ? (
          <ul className="mt-3 space-y-2">
            {c.recaps.map((r) => (
              <li key={r.token}>
                <Link
                  href={`/r/${encodeURIComponent(r.token)}`}
                  className="flex items-center justify-between rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-3 transition-colors hover:border-zinc-700"
                >
                  <span className="text-sm text-zinc-100">
                    {new Date(r.startedAt).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "America/New_York" })}
                  </span>
                  <span className="text-sm tabular-nums text-zinc-400">
                    {r.completed}/{r.planned} reps →
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-zinc-500">Your first recap shows up here after your workout.</p>
        )}
      </section>
    </div>
  );
}
