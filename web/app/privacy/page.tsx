import type { Metadata } from "next";

import { SiteHeader } from "@/components/site-header";

export const metadata: Metadata = {
  title: "Privacy · Brodie",
  description: "What Brodie sees during a workout, what it keeps, and who can see it.",
};

// Plain-language privacy notice for the pilot. Keep it true to what the code does: live calls are not recorded
// (facetime/worker.py streams frames, facetime/call_recap.py saves counts + the recap image only).
const SECTIONS: { title: string; body: React.ReactNode }[] = [
  {
    title: "During a workout",
    body: (
      <>
        Your camera and microphone are used live so Brodie can count reps, check form and talk to you. The call runs through
        LiveKit (and Chert, for FaceTime calls), and Brodie&apos;s voice and coaching run on Google Gemini, which receives your audio and occasional video frames
        while the call is on. <b className="text-ink">We don&apos;t record or store the video or audio of your call.</b>
      </>
    ),
  },
  {
    title: "What we keep",
    body: (
      <>
        Your name as your coach entered it, which workout you did and when, reps and sets per exercise, form flags (for
        example &quot;knees caved on rep 4&quot;), an estimated muscle heat map and the recap image shown at the end of the call.
      </>
    ),
  },
  {
    title: "Who can see it",
    body: (
      <>
        You (through your recap links) and your coach (on their dashboard). Links are long random codes, are hidden from
        search engines, and work for anyone who has them, so don&apos;t post your personal links publicly. We don&apos;t sell your
        data or use it for ads.
      </>
    ),
  },
  {
    title: "Coaches",
    body: (
      <>
        When you apply we keep what you put in the form (name, email, location, client count, Instagram or website and
        notes) to review your application and contact you about Brodie.
      </>
    ),
  },
  {
    title: "Deleting your data",
    body: (
      <>
        Ask your coach, or the Brodie team, to delete your workouts and we&apos;ll remove them. Brodie is a pilot made by a
        student team: it estimates reps and form and is not medical advice. Stop if anything hurts.
      </>
    ),
  },
];

export default function PrivacyPage() {
  return (
    <main className="flex flex-1 flex-col bg-canvas text-ink">
      <div className="mx-auto w-full max-w-2xl px-4 pb-16 pt-5">
        <SiteHeader context="Privacy" />
        <h1 className="mt-8 text-[28px] font-semibold tracking-[-0.025em] text-ink">Privacy</h1>
        <p className="mt-2 text-ink-2">The short version: Brodie watches live to coach you, and keeps the numbers, not the video.</p>
        <div className="mt-8 space-y-6">
          {SECTIONS.map((s) => (
            <section key={s.title}>
              <h2 className="text-base font-semibold text-ink">{s.title}</h2>
              <p className="mt-1 text-sm leading-relaxed text-ink-2">{s.body}</p>
            </section>
          ))}
        </div>
        <p className="mt-10 text-xs text-ink-3">Last updated October 11, 2026.</p>
      </div>
    </main>
  );
}
