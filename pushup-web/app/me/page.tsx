import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { currentAccessToken, fetchMe, webJoinEnabled } from "@/lib/me";
import { JoinForm } from "./join-form";
import { MeDashboard } from "./me-dashboard";
import { signOutUser } from "./actions";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "My spot", robots: { index: false, follow: false } };

export default async function MePage() {
  if (!webJoinEnabled()) notFound();
  const res = await fetchMe(await currentAccessToken());
  if (res.status === "unauthenticated") redirect("/login");

  return (
    <div className="mx-auto max-w-xl">
      {res.status === "error" ? (
        <div className="card p-6">
          <p className="eyebrow text-bad">Line unreachable</p>
          <p className="mt-2 text-lg">{res.message}</p>
          <Link href="/me" className="mt-4 inline-flex min-h-11 items-center font-semibold text-accent">
            Try again
          </Link>
        </div>
      ) : res.me.registered ? (
        <MeDashboard initial={res.me} />
      ) : (
        <JoinForm email={res.me.email} />
      )}
      <form action={signOutUser} className="mt-10 flex justify-center">
        <button type="submit" className="min-h-11 px-4 text-sm font-semibold text-ink-3 hover:text-ink">
          Sign out
        </button>
      </form>
    </div>
  );
}
