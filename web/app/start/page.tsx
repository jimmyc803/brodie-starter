import type { Metadata } from "next";

import { SignupForm } from "@/components/signup-form";
import { SiteHeader } from "@/components/site-header";

export const metadata: Metadata = {
  title: "Start coaching with Brodie",
  description: "Upload your program, send clients a link, and see every rep they do. Free during the pilot.",
};

const POINTS = [
  "Upload the PDF program you already use",
  "Send each client their own workout link: no app, no login",
  "Brodie counts every rep and coaches form out loud",
  "See who trained, how cleanly, and which sets need a look",
];

export default function StartPage() {
  return (
    <main className="flex-1 bg-zinc-950 text-zinc-100">
      <div className="mx-auto w-full max-w-4xl px-4 pb-16 pt-5 sm:px-6 sm:pt-8">
        <SiteHeader />
        <div className="mt-12 grid gap-10 md:grid-cols-2 md:items-start">
          <section>
            <h1 className="text-4xl font-bold tracking-tight text-balance text-zinc-50">Start coaching with Brodie</h1>
            <p className="mt-3 text-zinc-400">Your clients train with an AI coach that watches every rep. You see exactly how it went.</p>
            <ul className="mt-6 space-y-3">
              {POINTS.map((p) => (
                <li key={p} className="flex gap-3 text-sm text-zinc-300">
                  <span aria-hidden className="mt-1.5 size-1.5 shrink-0 rounded-full bg-green-500" />
                  {p}
                </li>
              ))}
            </ul>
          </section>
          <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-6">
            <SignupForm />
          </section>
        </div>
      </div>
    </main>
  );
}
