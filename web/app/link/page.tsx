import type { Metadata } from "next";
import Link from "next/link";

import { SiteHeader } from "@/components/site-header";
import { LinkForm } from "./form";

export const metadata: Metadata = {
  title: "Get your coach link · Brodie",
  description: "Lost your private coach link? We'll email it to you.",
  robots: { index: false, follow: false },
};

// "Email me my link": the coach dashboard has no password, so a lost link is recovered by email.
export default function LinkPage() {
  return (
    <main className="flex-1 bg-canvas text-ink">
      <div className="mx-auto w-full max-w-md px-4 pb-16 pt-5 sm:px-6 sm:pt-8">
        <SiteHeader />
        <h1 className="mt-12 text-[28px] font-semibold tracking-[-0.025em]">Get your coach link</h1>
        <p className="mt-2 text-ink-2">Your coach dashboard opens from a private link instead of a password. Enter your email and we&apos;ll send it again.</p>
        <section className="mt-6 rounded-[14px] border border-line bg-surface p-6">
          <LinkForm />
        </section>
        <p className="mt-4 text-sm text-ink-3">
          New to Brodie?{" "}
          <Link href="/start" className="font-semibold text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink">
            Apply to coach
          </Link>
        </p>
      </div>
    </main>
  );
}
