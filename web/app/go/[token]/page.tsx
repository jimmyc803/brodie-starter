import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { CallLauncher } from "@/components/call/call-launcher";
import { FaceTimeLauncher } from "@/components/call/facetime-launcher";
import { SiteHeader } from "@/components/site-header";
import { getClientHome } from "@/lib/client-view";
import { linesEnabled } from "@/lib/lines";

export const metadata: Metadata = {
  title: "Your workout · Brodie",
  description: "Train with Brodie: your coach's program, counted rep by rep.",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

// A client's personal link, /go/<clients.share_token>: today's workout, a button that starts the call, and past recaps.
export default function ClientHomePage({ params }: PageProps<"/go/[token]">) {
  return (
    <main className="flex flex-1 flex-col bg-canvas text-ink">
      <Suspense fallback={<div className="min-h-dvh" />}>
        <ClientHome params={params} />
      </Suspense>
    </main>
  );
}

async function ClientHome({ params }: Pick<PageProps<"/go/[token]">, "params">) {
  await connection(); // private, live data
  const { token } = await params;
  const [c, facetime] = await Promise.all([getClientHome(token), linesEnabled()]);
  if (!c) notFound();
  const first = c.name.split(" ")[0];
  return (
    <div className="mx-auto w-full max-w-md px-4 pb-12 pt-5">
      <SiteHeader context={`Coach ${c.coachName}`} />
      <h1 className="mt-8 text-[28px] font-semibold tracking-[-0.025em] text-ink">Hi {first} 👋</h1>
      <p className="mt-1 text-ink-2">Ready when you are. Brodie counts every rep and tells you how to fix your form.</p>

      <section className="mt-6 rounded-[14px] border border-line bg-surface p-5">
        <p className="text-sm text-ink-3">Today&apos;s workout</p>
        <p className="mt-0.5 text-xl font-semibold text-ink">{c.next ?? "Not assigned yet"}</p>
        <p className="mt-1 text-sm text-ink-2">
          {c.next ? `From Coach ${c.coachName}.` : `Coach ${c.coachName} hasn't picked your next workout yet. Check back soon.`}
        </p>
        {c.next ? (
          <div className="mt-5">
            {facetime ? <FaceTimeLauncher token={token} /> : <CallLauncher token={token} firstName={first} />}
          </div>
        ) : null}
      </section>

      <ul className="mt-4 space-y-1.5 text-sm text-ink-2">
        <li>{facetime ? "• Tap Start workout, then FaceTime Brodie from this phone (video call)." : "• Use Safari or Chrome and allow the camera when asked."}</li>
        <li>• Prop the phone up, step back until your whole body is in view.</li>
        <li>
          • Your camera is only used live to coach you; the call isn&apos;t recorded. Starting a workout means you agree to the{" "}
          <Link href="/privacy" className="text-ink-2 underline underline-offset-2">
            privacy notice
          </Link>
          .
        </li>
      </ul>

      <section className="mt-8">
        <h2 className="text-base font-semibold text-ink">Your recaps</h2>
        {c.recaps.length ? (
          <ul className="mt-3 space-y-2">
            {c.recaps.map((r) => (
              <li key={r.token}>
                <Link
                  href={`/r/${encodeURIComponent(r.token)}`}
                  className="flex items-center justify-between rounded-[10px] border border-line bg-surface px-4 py-3 transition-colors hover:border-line-strong"
                >
                  <span className="text-sm text-ink">
                    {new Date(r.startedAt).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "America/New_York" })}
                  </span>
                  <span className="text-sm tabular-nums text-ink-2">
                    {r.completed}/{r.planned} reps →
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-ink-3">Your first recap shows up here after your workout.</p>
        )}
      </section>
    </div>
  );
}
