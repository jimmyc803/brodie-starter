import type { Metadata } from "next";
import Link from "next/link";
import { CtaBand, PageIntro, SectionHeading } from "@/components/editorial";
import { DocLinks, Faq, P, Toc } from "@/components/legal";
import { getCompetition } from "@/lib/data";
import { formatEtDeadline, smsLink } from "@/lib/format";
import { ufcFighterCopy } from "@/lib/mappers";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "How it works",
  description:
    "Step by step: the texts to send, where to put your phone, what Brodie's screen shows, troubleshooting and answers to common questions.",
};

const TOC = [
  ["steps", "Step by step"],
  ["placement", "Phone placement"],
  ["screen", "Brodie's screen"],
  ["commands", "Commands"],
  ["trouble", "Troubleshooting"],
  ["faq", "FAQ"],
] as const;

const STEPS: [string, React.ReactNode][] = [
  [
    "Text JOIN + your name",
    <>
      Send <Code>JOIN your_name</Code> to Brodie, for example <Code>JOIN Marcus_T</Code>. Names are 3 to 20 letters, numbers or underscores, no spaces.
    </>,
  ],
  [
    "Reply YES",
    <>
      Brodie asks you to confirm you&apos;re 18+, in the US, and agree to the <Link href="/rules" className="font-semibold text-accent underline">rules</Link>. Text <Code>YES</Code> and you&apos;re in.
    </>,
  ],
  [
    "Text QUEUE",
    <>
      Send <Code>QUEUE</Code> (or <Code>Q</Code>) when you&apos;re ready to rep. Brodie texts your position, the wait and your calls left today. If the line is open, it says so: FaceTime right away.
    </>,
  ],
  [
    "Wait for \"You're up!\"",
    <>
      Brodie texts when it&apos;s your turn. You have <strong>90 seconds</strong> to start the FaceTime call (plus a few seconds of grace). Not ready? Text <Code>LEAVE</Code> and rejoin later.
    </>,
  ],
  [
    "FaceTime Brodie",
    <>
      Open FaceTime on your iPhone and call Brodie&apos;s number, the same one you text. Brodie answers and your <strong>3:00</strong> starts. Setup happens inside it, so have your phone placed first. Keep your camera on: Brodie can&apos;t count what it can&apos;t see.
    </>,
  ],
  [
    "Rep it out",
    <>
      Do strict push-ups. Brodie shows each rep live and says what to fix. At 3:00 counting stops and a 15 second reveal shows your result. At 3:15 Brodie hangs up for real.
    </>,
  ],
  [
    "Check your texts",
    <>
      Brodie texts your valid and rejected reps, points, rank, streak and a link to your result card. Up to 5 counted calls a day; text <Code>QUEUE</Code> to go again.
    </>,
  ],
];

function Code({ children }: { children: React.ReactNode }) {
  return <span className="border border-ink/30 bg-surface-2 px-1.5 py-0.5 font-mono text-[0.9em] font-bold text-ink">{children}</span>;
}

const COMMANDS: [string, string][] = [
  ["JOIN name", "Sign up with a display name (3 to 20 letters, numbers or underscores)."],
  ["YES", "Confirm you are 18+, in the US, and accept the rules."],
  ["QUEUE (Q, LINE)", "Get in line, or find out the line is open. Also turns texts back on after STOP."],
  ["STATUS (S, ME)", "Your points, valid reps, rank, calls left today, streak, queue spot and today's power hour."],
  ["TOP (LB, LEADERBOARD)", "The top 5 plus a link to the board."],
  ["LEAVE", "Leave the queue."],
  ["RULES", "A short rules summary and the link."],
  ["POWER", "Today's power hour."],
  ["HELP", "The list of commands."],
  ["DELETE MY DATA", "Ask us to delete your account and data. Done by the team within 30 days."],
  ["STOP", "Stop proactive texts and leave the queue. Always honored."],
  ["START", "Turn texts back on."],
];

export default async function HowItWorksPage() {
  const comp = await getCompetition();
  const end = formatEtDeadline(comp?.windowEnd ?? null) ?? "Sun Oct 18 · 11:59 PM ET";
  const prize = comp?.firstPrize ?? "$500";
  const fighter = ufcFighterCopy(comp?.ufcFighter);

  return (
    <div className="space-y-10 sm:space-y-14">
      <PageIntro
        eyebrow="How it works"
        title="Text. Call."
        accent="Rep."
        lede="Seven steps from your first text to your spot on the board. Every text to send is below, exactly as Brodie reads it."
      />

      <Toc items={TOC} />

      <section aria-labelledby="steps" className="space-y-5">
        <SectionHeading id="steps" index="01">
          Step by step
        </SectionHeading>
        <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {STEPS.map(([title, body], i) => (
            <li key={title} className="card relative overflow-hidden p-5">
              <span aria-hidden className="pointer-events-none absolute -top-3 -right-1 font-display text-9xl text-pink/25">
                {i + 1}
              </span>
              <span className="bg-ink px-1.5 py-0.5 font-mono text-xs font-bold text-canvas uppercase">Step {i + 1}</span>
              <span className="mt-2 block font-display text-2xl font-extrabold uppercase leading-tight">{title}</span>
              <span className="prose-brodie mt-1 block text-sm leading-relaxed text-ink-2">{body}</span>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="placement" className="space-y-5 border-t border-hairline pt-8">
        <SectionHeading id="placement" index="02">
          Phone placement
        </SectionHeading>
        <div className="prose-brodie grid gap-5 lg:grid-cols-2">
          <ul className="space-y-3">
            {[
              <>
                <strong>Prop it up on the floor or a low surface, a few feet away.</strong> Far enough that Brodie sees your upper body and your knees.
              </>,
              <>
                <strong>Side, diagonal or front view all work.</strong> The judge is lenient on camera angle. Side-on is still the easiest to read.
              </>,
              <>
                <strong>Sideways or upright, either is fine.</strong> Turn your phone sideways and Brodie&apos;s video switches to a landscape layout on its own; upright gets the portrait layout. Portrait lock is OK. No zooming or panning needed.
              </>,
              <>
                <strong>Upper body and knees in frame.</strong> Shoulders, elbows and wrists must be visible. Feet can be cut off.
              </>,
              <>
                <strong>Good light on you</strong>, nobody else in frame, and a clear patch of floor.
              </>,
            ].map((t, i) => (
              <li key={i} className="flex gap-3">
                <span aria-hidden className="mt-1 font-display text-pink">✶</span>
                <span className="leading-relaxed">{t}</span>
              </li>
            ))}
          </ul>
          <div className="card flex flex-col justify-center gap-3 p-5">
            <p className="font-display text-3xl uppercase leading-tight">Want the diagram?</p>
            <P>The setup guide has an illustrated checklist and the setups that cost people the most reps.</P>
            <Link href="/setup" className="press inline-flex min-h-11 w-fit items-center border-2 border-ink bg-yellow px-4 font-mono text-sm font-bold uppercase text-ink">
              Camera setup guide
            </Link>
          </div>
        </div>
      </section>

      <section aria-labelledby="screen" className="space-y-5 border-t border-hairline pt-8">
        <SectionHeading id="screen" index="03">
          What Brodie&apos;s screen shows
        </SectionHeading>
        <P>
          On the FaceTime call you see <strong>your own live video</strong> with a skeleton drawn on your body: green lines where you&apos;re
          doing it right, red where something is off (sagging hips, bent legs). It switches between a portrait and a landscape layout by itself, depending on how you hold your phone. On the video:
        </P>
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["CAMERA ANGLE GOOD", "bg-blue text-canvas", "Brodie can see you. Start repping."],
            ["SHOW HANDS TO KNEES", "bg-yellow text-ink", "Part of you is missing. Move the phone a bit further away."],
            ["GET IN PLANK", "bg-yellow text-ink", "Hands down, legs straight, body in plank."],
            ["CAN'T SEE YOU", "bg-pink text-ink", "No one found. Get in frame."],
          ].map(([pill, cls, note]) => (
            <li key={pill} className="card-flat p-4">
              <span className={`inline-block border-2 border-ink px-2 py-0.5 font-mono text-xs font-bold tracking-wider ${cls}`}>{pill}</span>
              <p className="mt-2 text-sm text-ink-2">{note}</p>
            </li>
          ))}
        </ul>
        <ul className="grid gap-2 sm:grid-cols-3">
          <li className="card-flat p-4">
            <span className="inline-block -rotate-2 border-2 border-ink bg-blue px-2 py-0.5 font-display text-lg uppercase text-canvas">Good rep +1</span>
            <p className="mt-2 text-sm text-ink-2">The verdict stamp after a rep that counts.</p>
          </li>
          <li className="card-flat p-4">
            <span className="inline-block rotate-2 border-2 border-ink bg-pink px-2 py-0.5 font-display text-lg uppercase text-ink">No rep · Go lower</span>
            <p className="mt-2 text-sm text-ink-2">The stamp for a rep that doesn&apos;t, with the main reason.</p>
          </li>
          <li className="card-flat p-4">
            <span className="inline-block border-2 border-ink bg-surface-2 px-2 py-0.5 font-display text-lg uppercase text-ink">12 valid reps</span>
            <p className="mt-2 text-sm text-ink-2">The valid-rep count stays on screen; the countdown timer is in the header.</p>
          </li>
        </ul>
        <P>Brodie also talks to you with short spoken cues like &ldquo;Lower!&rdquo; or &ldquo;lock those arms out&rdquo;, and calls &ldquo;thirty seconds left&rdquo;. When several things are off, you hear the most useful fix first, and the same cue never repeats within 10 seconds.</P>
      </section>

      <section aria-labelledby="commands" className="space-y-5 border-t border-hairline pt-8">
        <SectionHeading id="commands" index="04">
          Texts Brodie understands
        </SectionHeading>
        <dl className="card divide-y divide-hairline-strong">
          {COMMANDS.map(([cmd, what]) => (
            <div key={cmd} className="grid gap-1 px-4 py-3 sm:grid-cols-[14rem_minmax(0,1fr)] sm:gap-6">
              <dt className="font-mono text-sm font-bold text-ink">{cmd}</dt>
              <dd className="text-ink-2">{what}</dd>
            </div>
          ))}
        </dl>
        <P>Commands aren&apos;t case sensitive, and small typos are forgiven. Anything else gets the command list back.</P>
      </section>

      <section aria-labelledby="trouble" className="space-y-5 border-t border-hairline pt-8">
        <SectionHeading id="trouble" index="05">
          Troubleshooting
        </SectionHeading>
        <div className="space-y-2">
          <Faq q="The line is busy or nobody picks up">
            <P>
              Brodie takes one caller at a time. Text <Code>QUEUE</Code> and wait for the &ldquo;you&apos;re up&rdquo; text, then call. Between
              callers the line rests for a few minutes.
            </P>
          </Faq>
          <Faq q="Brodie hung up right away, or said “Not your turn”">
            <P>
              That means it wasn&apos;t your turn. Only the person who got the &ldquo;you&apos;re up&rdquo; text can start a call, and nothing is
              recorded. If you called while you were in line, Brodie texts you your spot. Brodie says: &ldquo;Not your turn! Text this number JOIN, then QUEUE. I&apos;ll text you when you&apos;re up.&rdquo; Other reasons:
              you haven&apos;t joined yet, you&apos;ve used today&apos;s 5 calls, your 90 seconds ran out, or the Challenge isn&apos;t open. Text
              <Code>STATUS</Code> to see where you stand.
            </P>
          </Faq>
          <Faq q="I missed my 90 seconds">
            <P>You get 90 seconds from the &ldquo;you&apos;re up&rdquo; text, plus about 10 seconds of grace if you&apos;re already dialing. After that you lose that spot, nothing else. Text <Code>QUEUE</Code> to get back in line.</P>
          </Faq>
          <Faq q="My reps aren't counting">
            <P>Check the stamp on the screen. The reason is right there:</P>
            <ul className="list-disc space-y-1 pl-5 text-ink-2">
              <li><strong>GO LOWER:</strong> chest down until your elbows bend to about 90 to 125 degrees.</li>
              <li><strong>LOCK OUT AT THE TOP:</strong> straighten your arms fully before the next rep.</li>
              <li><strong>KNEES DOWN:</strong> knee push-ups don&apos;t count. Stay on your toes.</li>
              <li><strong>HIPS SAGGING / HIPS TOO HIGH:</strong> keep a straight line from shoulders to ankles.</li>
              <li><strong>STAY IN FRAME:</strong> move the phone back until the pill says CAMERA ANGLE GOOD.</li>
              <li><strong>ONE PERSON ONLY:</strong> no one else in the picture.</li>
              <li><strong>TOO FAST:</strong> no bouncing. About half a second per rep or slower.</li>
              <li><strong>GET IN PLANK:</strong> your body should be roughly flat, not standing or on a high surface.</li>
            </ul>
          </Faq>
          <Faq q="The camera pill says CAN'T SEE YOU or SHOW HANDS TO KNEES">
            <P>
              Move the phone a bit further away and check the angle so your shoulders, elbows and wrists show. Turn on a light in front of you. Don&apos;t sit
              in front of a bright window.
            </P>
          </Faq>
          <Faq q="My call dropped">
            <P>
              If a call on your turn ends in under 30 seconds with no valid reps (someone else grabbed the line, or the call dropped), it does
              not count toward your 5 a day and you get your turn back once: Brodie sends a new &ldquo;you&apos;re up&rdquo; text. After that, or
              for a longer call, a new call needs a new turn: text <Code>QUEUE</Code>. A call counts toward your daily 5 if it lasted 30
              seconds or you made a rep.
            </P>
          </Faq>
          <Faq q="Brodie says “I can’t see you!”">
            <P>
              Your camera is off or blocked. Turn it on so Brodie can count. If it stays off, Brodie hangs up after about 20 seconds.
            </P>
          </Faq>
          <Faq q="Brodie said “Something glitched on my end”">
            <P>
              Something failed while the call was starting. Hang up and call back in a minute. If it happened on your turn and the call
              was short with no reps, it doesn&apos;t count toward your daily 5.
            </P>
          </Faq>
          <Faq q="When does the call end?">
            <P>Counting stops at 3:00, a 15 second reveal follows, and Brodie hangs up at 3:15. Anything after 3:00 doesn&apos;t score.</P>
          </Faq>
          <Faq q="I don't get Brodie's texts">
            <P>
              If you texted STOP, text <Code>START</Code> (or <Code>QUEUE</Code>). Brodie sends nothing proactive between 11 PM and 9 AM ET apart from
              &ldquo;you&apos;re up&rdquo; and results. Text <Code>HELP</Code> to check Brodie hears you.
            </P>
          </Faq>
        </div>
      </section>

      <section aria-labelledby="faq" className="space-y-5 border-t border-hairline pt-8">
        <SectionHeading id="faq" index="06">
          FAQ
        </SectionHeading>
        <div className="space-y-2">
          <Faq q="What is power hour?">
            <P>
              One hour a day at a random start between 12:00 and 22:00 ET. Valid reps inside it score double. Brodie announces it in the morning
              recap, 15 minutes before and at the start. Text <Code>POWER</Code> to see today&apos;s.
            </P>
          </Faq>
          <Faq q="How many times can I call?">
            <P>
              Up to 5 counted calls per day. The count resets at midnight ET. A call counts if you were connected for 30 seconds or made at least
              one rep. Fewest calls today goes first in the queue.
            </P>
          </Faq>
          <Faq q="What happens in a tie?">
            <P>Whoever reached the tied total first ranks higher.</P>
          </Faq>
          <Faq q="What are the prizes?">
            <P>
              1st place wins {prize}. The top 3 get a group call with {fighter}. The challenge ends {end}, then the top 3 do a verification call before
              anything is paid. Details in the <Link href="/rules#prizes" className="font-semibold text-accent underline">rules</Link>.
            </P>
          </Faq>
          <Faq q="Is my video recorded?">
            <P>
              No. No video or audio is ever stored. Brodie analyzes your call live, in memory, and keeps only rep counts, measurements and cue logs. Your
              phone number is never shown; the board uses your display name. See the <Link href="/privacy" className="font-semibold text-accent underline">privacy policy</Link>.
            </P>
          </Faq>
          <Faq q="Do knee push-ups or modified push-ups count?">
            <P>
              No. The judge only counts push-ups from your toes, with your chest down and arms locked out. There is no separate category for modified
              push-ups, so they don&apos;t score. You can still follow along on the board.
            </P>
          </Faq>
          <Faq q="Can I have more than one account?">
            <P>
              No. One person, one account. Reps stay with the account that did them, so extra accounts give no advantage, and cheating gets accounts removed.
            </P>
          </Faq>
          <Faq q="Who can play?">
            <P>People who are 18 or older, in the US, with an iPhone.</P>
          </Faq>
          <Faq q="What if I think the judge got it wrong?">
            <P>
              Text <Code>HELP</Code> or reply to Brodie with what happened and when. The team can review calls and fix scores. The judge&apos;s count and the
              team&apos;s decisions are final.
            </P>
          </Faq>
          <Faq q="How do I quit and delete my data?">
            <P>
              Text <Code>STOP</Code> to stop texts and leave the queue. To delete your data, text <Code>DELETE MY DATA</Code>. See the{" "}
              <Link href="/privacy#delete" className="font-semibold text-accent underline">privacy policy</Link>.
            </P>
          </Faq>
        </div>
        <DocLinks current="/how-it-works" />
      </section>

      <CtaBand
        joinHref={smsLink(comp?.brodieNumber ?? null)}
        title="Ready to rep?"
        body="Text JOIN with your name, reply YES, then text QUEUE."
      />
    </div>
  );
}
