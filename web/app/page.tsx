import Image from "next/image";
import Link from "next/link";

import { SiteHeader } from "@/components/site-header";
import { BrodieCallFace } from "@/components/ui-kit/brodie";

// Landing page for coaches: what Brodie does, proof (the live demos), and every call to action goes to /start.
const STEPS = [
  { title: "Upload your program", body: "The PDF you already use. Brodie reads the days, exercises, sets and reps." },
  { title: "Send each client their link", body: "They tap it and FaceTime Brodie, which counts every rep and cues form out loud." },
  { title: "See how it went", body: "A recap with a muscle heat map for the client, and an inbox of who needs you." },
];
const FEATURES = [
  { title: "Triage inbox", body: "Clients who need you come first: flagged sets, short sessions, missed workouts." },
  { title: "Form flags with clips", body: "Tap a muscle to watch the reps behind it, with what Brodie cued." },
  { title: "Built for big rosters", body: "Search, filters and keyboard navigation for coaches with dozens of clients." },
];
const FAQ = [
  { q: "What does my client need?", a: "A phone with FaceTime and their link from you. No app, no account." },
  { q: "Is the video private?", a: "Recaps are private links. Read exactly what we keep in our privacy notice." },
  { q: "What does it cost?", a: "Free during the pilot. We review every coach and onboard you personally." },
];

export default function Home() {
  return (
    <main className="flex-1 bg-canvas text-ink">
      <div className="mx-auto w-full max-w-5xl px-4 pb-20 pt-5 sm:px-6 sm:pt-8">
        <SiteHeader
          context={
            <>
              <Link href="/c/demo" className="hidden text-ink-2 hover:text-ink sm:inline">
                Coach demo
              </Link>
              <Link href="/start" className="rounded-[10px] bg-brand px-3.5 py-2 text-sm font-semibold text-on-brand hover:brightness-95">
                Apply to coach
              </Link>
            </>
          }
        />

        <div className="mt-16 grid items-center gap-12 sm:mt-24 md:grid-cols-[minmax(0,1fr)_260px]">
        <section className="max-w-2xl">
          <p className="text-[12.5px] font-medium text-ink-3">For online coaches and busy trainers</p>
          <h1 className="mt-2 text-[40px] font-semibold leading-[1.03] tracking-[-0.03em] text-balance sm:text-[56px]">
            Eyes on every rep, even when you&apos;re not there.
          </h1>
          <p className="mt-5 text-lg leading-relaxed text-ink-2">
            Your client FaceTimes Brodie, an AI coach that runs your program, counts reps on camera and cues form out loud.
            You get a recap of every set and an inbox of who needs you.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/start" className="rounded-[10px] bg-ink px-5 py-3 text-sm font-semibold text-canvas hover:opacity-90">
              Start coaching with Brodie
            </Link>
            <Link href="/r/demo" className="rounded-[10px] border border-line-strong px-5 py-3 text-sm font-semibold text-ink hover:bg-sunken">
              See a client recap
            </Link>
          </div>
          <p className="mt-3 text-xs text-ink-3">Free during the pilot. Takes a minute.</p>
        </section>
        <figure className="mx-auto w-full max-w-[260px]">
          <BrodieCallFace />
          <figcaption className="mt-3 text-center text-sm text-ink-2">This is who your client FaceTimes.</figcaption>
        </figure>
        </div>

        <ol className="mt-20 grid gap-3 sm:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="rounded-[14px] border border-line bg-surface p-5">
              <span className="text-[12.5px] font-medium text-ink-3">Step {i + 1}</span>
              <h2 className="mt-1 text-[17px] font-semibold">{s.title}</h2>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{s.body}</p>
            </li>
          ))}
        </ol>

        <section className="mt-20">
          <h2 className="text-[26px] font-semibold tracking-[-0.025em]">Built for coaches with a lot of clients</h2>
          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            {FEATURES.map((f) => (
              <div key={f.title} className="rounded-[14px] border border-line bg-surface p-5">
                <h3 className="font-semibold">{f.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{f.body}</p>
              </div>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-4 text-sm">
            <Link href="/c/demo" className="font-semibold underline decoration-line-strong underline-offset-4 hover:decoration-ink">
              Open the coach demo →
            </Link>
            <Link href="/r/demo" className="font-semibold underline decoration-line-strong underline-offset-4 hover:decoration-ink">
              Open a client recap →
            </Link>
          </div>
        </section>

        <section className="mt-20 grid gap-6 sm:grid-cols-3">
          {FAQ.map((f) => (
            <div key={f.q}>
              <h3 className="font-semibold">{f.q}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-2">
                {f.a}
                {f.q.startsWith("Is the video") ? (
                  <>
                    {" "}
                    <Link href="/privacy" className="font-semibold text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink">
                      Privacy notice
                    </Link>
                  </>
                ) : null}
              </p>
            </div>
          ))}
        </section>

        <section className="mt-20 rounded-[18px] border border-line bg-surface p-6 text-center sm:p-10">
          <Image src="/brodie/flex.png" alt="" width={110} height={112} className="mx-auto mb-4" />
          <h2 className="text-[26px] font-semibold tracking-[-0.025em] text-balance">Coach more clients without losing the details</h2>
          <Link href="/start" className="mt-5 inline-block rounded-[10px] bg-ink px-5 py-3 text-sm font-semibold text-canvas hover:opacity-90">
            Apply to coach with Brodie
          </Link>
        </section>

        <footer className="mt-16 flex gap-4 border-t border-line pt-6 text-xs text-ink-3">
          <span>© Brodie for Coaches</span>
          <Link href="/privacy" className="hover:text-ink">
            Privacy
          </Link>
        </footer>
      </div>
    </main>
  );
}
