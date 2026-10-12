import type { Metadata } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ACCESS_COOKIE, checkAdmin } from "@/lib/admin";
import { signOut } from "../actions";
import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Admin sign-in", robots: { index: false, follow: false } };

const ERRORS: Record<string, string> = {
  forbidden: "This account is not on the admin allowlist.",
  link: "That sign-in link is invalid or expired. Request a new code.",
};

export default async function AdminLoginPage({ searchParams }: { searchParams: Promise<{ error?: string | string[] }> }) {
  const sp = await searchParams;
  const store = await cookies();
  let check: Awaited<ReturnType<typeof checkAdmin>> = { status: "unauthenticated" };
  try {
    check = await checkAdmin(store.get(ACCESS_COOKIE)?.value);
  } catch (e) {
    console.error("[admin] login page session check failed", e);
  }
  if (check.status === "ok") redirect("/admin");
  const errKey = typeof sp.error === "string" ? sp.error : "";
  const error = check.status === "forbidden" ? ERRORS.forbidden : ERRORS[errKey];

  return (
    <div className="mx-auto max-w-sm space-y-4 rounded-xl border border-hairline bg-surface p-5">
      <h1 className="font-display text-2xl uppercase tracking-wide text-accent">Admin sign-in</h1>
      {error && (
        <p role="alert" className="text-xs font-semibold text-bad">
          {error}
        </p>
      )}
      {check.status === "forbidden" ? (
        <form action={signOut} className="space-y-2 text-xs text-ink-2">
          <p>Signed in as {check.email}.</p>
          <button type="submit" className="rounded-md border border-hairline px-3 py-1.5 font-semibold text-ink hover:border-accent">
            Sign out
          </button>
        </form>
      ) : (
        <LoginForm />
      )}
    </div>
  );
}
