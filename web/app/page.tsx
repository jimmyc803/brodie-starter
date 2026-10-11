import Link from "next/link";

import { SiteHeader } from "@/components/site-header";

const STEPS = [
  { n: "1", title: "Coach uploads a program", body: "A PDF they already use. Brodie reads the days, exercises, sets and reps." },
  { n: "2", title: "Client FaceTimes Brodie", body: "Brodie counts every rep on camera, cues form out loud and talks between sets." },
  { n: "3", title: "Everyone sees how it went", body: "A recap with a muscle heat map for the client, and a dashboard for the coach." },
];

export default function Home() {
  return (
    <main className="flex-1 bg-zinc-950 text-zinc-100">
      <div className="mx-auto w-full max-w-4xl px-4 pb-16 pt-5 sm:px-6 sm:pt-8">
        <SiteHeader context={<Link href="/start" className="text-zinc-300 hover:text-zinc-50">For coaches →</Link>} />

        <section className="mt-16 max-w-2xl sm:mt-24">
          <h1 className="text-4xl font-bold tracking-tight text-balance text-zinc-50 sm:text-5xl">
            Your program, coached rep by rep.
          </h1>
          <p className="mt-4 text-lg text-zinc-400">
            Coaches write the program. Brodie runs the workout over FaceTime. Coaches see exactly how it went. No app
            to install, no account to make.
          </p>
          <div className="mt-8 flex flex-wrap gap-3 text-sm">
            <Link
              href="/start"
              className="rounded-full bg-green-500 px-5 py-2.5 font-semibold text-zinc-950 transition-colors hover:bg-green-400"
            >
              Start coaching with Brodie
            </Link>
            <Link
              href="/r/demo"
              className="rounded-full border border-zinc-700 px-5 py-2.5 font-medium text-zinc-100 transition-colors hover:border-zinc-500"
            >
              See a client recap
            </Link>
            <Link
              href="/c/demo"
              className="rounded-full border border-zinc-700 px-5 py-2.5 font-medium text-zinc-100 transition-colors hover:border-zinc-500"
            >
              See the coach dashboard
            </Link>
          </div>
          <p className="mt-3 text-xs text-zinc-500">Free during the pilot. Takes a minute.</p>
        </section>

        <ol className="mt-16 grid gap-3 sm:mt-24 sm:grid-cols-3">
          {STEPS.map((s) => (
            <li key={s.n} className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
              <span className="grid size-7 place-items-center rounded-full bg-zinc-800 text-sm font-semibold text-zinc-300">
                {s.n}
              </span>
              <h2 className="mt-4 font-semibold text-zinc-50">{s.title}</h2>
              <p className="mt-1 text-sm leading-relaxed text-zinc-400">{s.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </main>
  );
}
