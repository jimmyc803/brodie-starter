import { Camera, FileText, LayoutDashboard } from "lucide-react";

import { SiteHeader } from "@/components/site-header";
import { PillLink, Stage, Surface } from "@/components/ui/apple";

const STEPS = [
  {
    Icon: FileText,
    title: "Upload the program",
    body: "Drop in the PDF you already use. Brodie reads the days, exercises, sets and reps.",
  },
  {
    Icon: Camera,
    title: "Train over FaceTime",
    body: "Brodie counts every rep on camera, cues form out loud and keeps pace between sets.",
  },
  {
    Icon: LayoutDashboard,
    title: "See how it went",
    body: "Clients get a recap with a muscle heat map. Coaches get a dashboard of every session.",
  },
];

export default function Home() {
  return (
    <main className="flex-1 bg-canvas text-ink">
      <SiteHeader context="IvyHacks 2026" />

      <div className="mx-auto w-full max-w-[980px] px-5 sm:px-6">
        <section className="flex flex-col items-center pb-16 pt-20 text-center sm:pb-24 sm:pt-32">
          <h1 className="t-hero max-w-[16ch] text-balance">Your program, coached rep by rep.</h1>
          <p className="t-body mt-5 max-w-[34rem] text-balance text-ink-2">
            Write the program. Brodie runs the workout over FaceTime, and you see exactly how it went. No app to
            install, no account to make.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <PillLink href="/r/demo" variant="primary" size="lg">
              See a client recap
            </PillLink>
            <PillLink href="/c/demo" variant="secondary" size="lg">
              Open the coach dashboard
            </PillLink>
          </div>
        </section>

        <ol className="grid gap-4 sm:grid-cols-3">
          {STEPS.map(({ Icon, title, body }) => (
            <Surface as="li" key={title} className="p-6">
              <Icon className="size-6 text-ink-2" strokeWidth={1.5} aria-hidden />
              <h2 className="t-title-2 mt-6">{title}</h2>
              <p className="t-callout mt-2 text-ink-2">{body}</p>
            </Surface>
          ))}
        </ol>

        <Stage className="mt-4 overflow-hidden px-6 pb-10 pt-12 text-center sm:px-12 sm:pt-16">
          <h2 className="t-display mx-auto max-w-[20ch] text-balance">Every set, in one glance.</h2>
          <p className="t-body mx-auto mt-4 max-w-[32rem] text-on-stage-2">
            The recap shows reps, form and the muscles worked. Clients open it from a private link.
          </p>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/api/recap-image/demo"
            alt="A workout recap card with a muscle heat map"
            className="mx-auto mt-10 block w-full max-w-[520px] rounded-[20px]"
          />
        </Stage>

        <footer className="mt-16 border-t border-hairline py-6 sm:mt-24">
          <p className="t-footnote text-ink-3">IvyHacks 2026 · Team Beat Muse</p>
        </footer>
      </div>
    </main>
  );
}
