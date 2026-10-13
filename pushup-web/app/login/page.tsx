import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { currentAccessToken, fetchMe, webJoinEnabled } from "@/lib/me";
import { LoginForm } from "./login-form";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Sign in", robots: { index: false, follow: false } };

const ERRORS: Record<string, string> = {
  link: "That sign-in link is invalid, expired, or was opened in a different browser. Request a new code here.",
  forbidden: "That account can't sign in here.",
};

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string | string[] }> }) {
  if (!webJoinEnabled()) notFound();
  const token = await currentAccessToken();
  if (token && (await fetchMe(token)).status === "ok") redirect("/me");
  const sp = await searchParams;
  const error = typeof sp.error === "string" ? ERRORS[sp.error] : undefined;

  return (
    <div className="mx-auto max-w-md">
      <p className="eyebrow text-accent">Your spot in line</p>
      <h1 className="mt-3 font-display text-hero font-extrabold uppercase italic tracking-tight">
        Sign <span className="text-accent">in.</span>
      </h1>
      <p className="mt-3 text-ink-2">
        We email you a 6-digit code. No password. Your email is never shown; only the name you pick is public.
      </p>
      {error ? (
        <p role="alert" className="mt-5 rounded-[var(--radius-card)] border border-bad/40 bg-bad/10 px-4 py-3 text-sm font-semibold text-bad">
          {error}
        </p>
      ) : null}
      <div className="card mt-6 p-5 sm:p-6">
        <LoginForm />
      </div>
    </div>
  );
}
