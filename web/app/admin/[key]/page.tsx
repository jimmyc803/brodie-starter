import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { SiteHeader } from "@/components/site-header";
import { isAdminKey } from "@/lib/admin";
import { supabaseServer } from "@/lib/supabase/server";
import { reviewCoachAction } from "./actions";

export const metadata: Metadata = { title: "Coach applications · Brodie", robots: { index: false, follow: false }, referrer: "no-referrer" };

type Application = { where?: string; clients?: string; website?: string | null; certification?: string | null; note?: string | null };
type Row = {
  id: string;
  name: string;
  email: string | null;
  instagram: string | null;
  status: "pending" | "approved" | "rejected";
  share_token: string;
  created_at: string;
  reviewed_at: string | null;
  application: Application | null;
  clients: { count: number }[];
  programs: { count: number }[];
};

// The team's review queue for coach applications from /start.
export default function AdminPage({ params }: PageProps<"/admin/[key]">) {
  return (
    <main className="flex-1 bg-canvas text-ink">
      <Suspense fallback={<div className="min-h-dvh" />}>
        <Admin params={params} />
      </Suspense>
    </main>
  );
}

async function Admin({ params }: Pick<PageProps<"/admin/[key]">, "params">) {
  await connection();
  const { key } = await params;
  if (!isAdminKey(key)) notFound();
  const { data, error } = await supabaseServer()
    .from("coaches")
    .select("id, name, email, instagram, status, share_token, created_at, reviewed_at, application, clients(count), programs(count)")
    .eq("signup_source", "web")
    .order("created_at", { ascending: false })
    .limit(200);
  if (error) return <p className="p-8 text-bad">Could not load applications: {error.message}</p>;
  const rows = (data ?? []) as unknown as Row[];
  const by = (s: Row["status"]) => rows.filter((r) => r.status === s);
  const review = reviewCoachAction.bind(null, key);
  return (
    <div className="mx-auto w-full max-w-5xl px-4 pb-16 pt-5 sm:px-6 sm:pt-8">
      <SiteHeader context="Team only" />
      <h1 className="mt-8 text-[28px] font-semibold tracking-[-0.025em]">Coach applications</h1>
      <p className="mt-1 text-sm text-ink-2">
        {by("pending").length} waiting · {by("approved").length} approved · {by("rejected").length} rejected
      </p>
      {(["pending", "approved", "rejected"] as const).map((status) => (
        <section key={status} className="mt-8">
          <h2 className="text-base font-semibold text-ink">{status === "pending" ? "Waiting for review" : status === "approved" ? "Approved" : "Rejected"}</h2>
          {by(status).length === 0 ? <p className="mt-2 text-sm text-ink-3">None.</p> : null}
          <ul className="mt-3 space-y-3">
            {by(status).map((r) => (
              <Card key={r.id} r={r} review={review} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function Card({ r, review }: { r: Row; review: (form: FormData) => Promise<void> }) {
  const a = r.application ?? {};
  const first = r.name.split(" ")[0];
  const dash = `https://brodie-for-coaches.vercel.app/c/${r.share_token}`;
  const mail = `mailto:${r.email}?subject=${encodeURIComponent("You're in: Brodie for Coaches")}&body=${encodeURIComponent(
    `Hi ${first},\n\nYou're approved for the Brodie pilot! Your dashboard: ${dash}\n(Keep this link private: it's your login.)\n\nWant a quick 15-minute setup call? We'll upload your first program and get your first clients training together.\n\nThe Brodie team`,
  )}`;
  const site = a.website ? (a.website.startsWith("http") ? a.website : `https://${a.website}`) : null;
  return (
    <li className="rounded-[14px] border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-lg font-semibold text-ink">{r.name}</p>
          <p className="text-sm text-ink-2">
            {r.email} · applied {new Date(r.created_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/New_York" })}
          </p>
        </div>
        <form action={review} className="flex gap-2">
          <input type="hidden" name="id" value={r.id} />
          {r.status !== "approved" ? (
            <button name="decision" value="approved" className="rounded-[10px] bg-brand px-4 py-1.5 text-sm font-semibold text-on-brand">
              Approve
            </button>
          ) : null}
          {r.status !== "rejected" ? (
            <button name="decision" value="rejected" className="rounded-full border border-line-strong px-4 py-1.5 text-sm text-ink-2">
              Reject
            </button>
          ) : null}
          {r.status !== "pending" ? (
            <button name="decision" value="pending" className="rounded-full px-3 py-1.5 text-sm text-ink-3 hover:text-ink">
              Undo
            </button>
          ) : null}
        </form>
      </div>
      <dl className="mt-4 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <Item label="Coaches at" value={a.where} />
        <Item label="Active clients" value={a.clients} />
        <Item label="Instagram" value={r.instagram ? <a className="text-good hover:underline" href={`https://instagram.com/${r.instagram}`} target="_blank" rel="noreferrer">@{r.instagram}</a> : null} />
        <Item label="Website" value={site ? <a className="text-good hover:underline" href={site} target="_blank" rel="noreferrer">{a.website}</a> : null} />
        <Item label="Certification" value={a.certification} />
        <Item label="In the sandbox" value={`${r.programs?.[0]?.count ?? 0} program(s) uploaded · ${r.clients?.[0]?.count ?? 0} client(s)`} />
      </dl>
      {a.note ? <p className="mt-3 rounded-[10px] bg-canvas px-3 py-2 text-sm text-ink-2">“{a.note}”</p> : null}
      {r.status === "approved" ? (
        <a href={mail} className="mt-4 inline-block rounded-full bg-ink px-4 py-1.5 text-sm font-medium text-canvas">
          Email {first} their dashboard link
        </a>
      ) : null}
    </li>
  );
}

function Item({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <dt className="w-28 shrink-0 text-ink-3">{label}</dt>
      <dd className="min-w-0 truncate text-ink">{value || <span className="text-ink-3">–</span>}</dd>
    </div>
  );
}
