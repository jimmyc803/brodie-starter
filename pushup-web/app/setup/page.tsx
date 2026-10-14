import type { Metadata } from "next";
import { CtaBand, PageIntro, SectionHeading } from "@/components/editorial";
import { SetupDiagram } from "@/components/setup-diagram";
import { CheckIcon, XIcon } from "@/components/ui/icons";
import { DocLinks } from "@/components/legal";
import { getCompetition } from "@/lib/data";
import { smsLink } from "@/lib/format";

export const metadata: Metadata = {
  title: "Setup",
  description: "Get your phone in position in 30 seconds so every strict rep gets counted.",
};

const CHECKLIST = [
  ["Phone low, to your side or in front", "On the floor or a low surface, about 6–8 feet away. Closer is fine if your upper body and knees stay in frame. Side, diagonal and front-on all work, propped up or flat. Behind your feet is the one spot to avoid."],
  ["Phone sideways", "Lay your phone sideways (landscape) on the floor or a prop. Brodie's video is a sideways full-screen layout, so it reads upright on a sideways phone. No zoom or pan."],
  ["Upper body and knees in frame", "Shoulders, elbows and wrists must show. Feet can be cut off. Check the pill says CAMERA ANGLE GOOD."],
  ["Camera on", "Keep it on the whole call. If Brodie can't see you, it says so and hangs up after about 20 seconds."],
  ["Light on you", "No bright window or lamp behind you."],
  ["Only you", "Nobody walking behind you while you rep."],
  ["Room to go flat", "Clear floor. Shoes or grippy socks."],
] as const;

const DONTS = [
  "Arms or shoulders cut off",
  "Propped far above you, looking down",
  "Someone else in the shot",
  "Backlit by a window",
];

export default async function SetupPage() {
  const comp = await getCompetition();
  return (
    <div className="space-y-10 sm:space-y-14">
      <PageIntro
        eyebrow="Setup guide"
        title="Set up in"
        accent="30 seconds."
        lede="Setup happens inside your 3:00 counting window. Nail the angle before you connect and every strict rep lands."
        art={<SetupDiagram />}
      />

      <section aria-labelledby="checklist" className="space-y-5">
        <SectionHeading id="checklist" index="01">
          The checklist
        </SectionHeading>
        <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {CHECKLIST.map(([title, body], i) => (
            <li key={title} className="card flex gap-4 p-4 sm:p-5">
              <span
                aria-hidden
                className="font-display text-5xl leading-[0.8] type-outline"
              >
                {i + 1}
              </span>
              <span>
                <span className="block font-display text-xl font-extrabold uppercase leading-tight">{title}</span>
                <span className="mt-0.5 block text-sm leading-relaxed text-ink-2">{body}</span>
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="avoid" className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-4">
          <SectionHeading id="avoid" index="02">
            Instant no-reps
          </SectionHeading>
          <p className="max-w-md text-ink-2">
            If the judge can&apos;t see your shoulders, elbows and wrists, it can&apos;t count the rep. These
            setups cost people the most reps.
          </p>
        </div>
        <ul className="grid grid-cols-2 gap-2">
          {DONTS.map((d) => (
            <li key={d} className="flex items-start gap-2 rounded-[var(--radius-card)] border border-bad/30 bg-bad/5 p-3 sm:p-4">
              <XIcon className="mt-0.5 size-4 shrink-0 text-bad" />
              <span className="text-sm font-semibold leading-snug">{d}</span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="go" className="card grid gap-4 p-5 sm:grid-cols-3 sm:p-8">
        <h2 id="go" className="font-display text-3xl font-extrabold uppercase leading-none sm:col-span-3">
          When the call connects
        </h2>
        {[
          ["Get in plank", "Arms locked, body straight, side-on to the camera."],
          ["Watch the clock", "Your 3:00 started when you connected. At 3:15 Brodie hangs up."],
          ["Rep it out", "Strict and steady beats fast and sloppy. Every rep is judged."],
        ].map(([t, d]) => (
          <div key={t} className="flex gap-3">
            <CheckIcon className="mt-1 size-5 shrink-0 text-accent" />
            <div>
              <p className="font-semibold">{t}</p>
              <p className="text-sm text-ink-2">{d}</p>
            </div>
          </div>
        ))}
      </section>

      <DocLinks current="/setup" />

      <CtaBand
        joinHref={smsLink(comp?.brodieNumber ?? null)}
        title="Set? Get in line."
        body="Text JOIN to sign up, then QUEUE when you're ready to rep. New here? See how it all works."
      />
    </div>
  );
}
