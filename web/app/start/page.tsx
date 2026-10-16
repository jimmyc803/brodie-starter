import type { Metadata } from "next";
import Link from "next/link";

import { SignupForm } from "@/components/signup-form";
import { SiteHeader } from "@/components/site-header";

export const metadata: Metadata = {
  title: "Apply to coach with Brodie",
  description: "Upload your program, send clients a link, and see every rep they do. Free during the pilot; we review every coach.",
};

const POINTS = [
  "Upload the PDF program you already use",
  "Send each client their own workout link: no app, no login",
  "Brodie counts every rep and coaches form out loud",
  "See who trained, how cleanly, and which sets need a look",
];

export default function StartPage() {
  return (
    <main className="flex-1 bg-canvas text-ink">
      <div className="mx-auto w-full max-w-4xl px-4 pb-16 pt-5 sm:px-6 sm:pt-8">
        <SiteHeader />
        <div className="mt-12 grid gap-10 md:grid-cols-2 md:items-start">
          <section>
            <h1 className="text-[34px] font-semibold tracking-[-0.025em] text-balance text-ink">Coach with Brodie</h1>
            <p className="mt-3 text-ink-2">Your clients train with an AI coach that watches every rep. You see exactly how it went. We&apos;re onboarding a small group of working coaches for the pilot.</p>
            <ul className="mt-6 space-y-3">
              {POINTS.map((p) => (
                <li key={p} className="flex gap-3 text-sm text-ink-2">
                  <span aria-hidden className="mt-1.5 size-1.5 shrink-0 rounded-full bg-brand" />
                  {p}
                </li>
              ))}
            </ul>
          </section>
          <div>
            <section className="rounded-[14px] border border-line bg-surface p-6">
              <SignupForm />
            </section>
            <p className="mt-4 text-sm text-ink-3">
              Already applied?{" "}
              <Link href="/link" className="font-semibold text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink">
                Email me my link
              </Link>
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}
