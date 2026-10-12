import type { Metadata } from "next";
import Link from "next/link";
import { PageIntro, SectionHeading } from "@/components/editorial";
import { JoinButton } from "@/components/join-button";
import { ArrowRightIcon, CheckIcon } from "@/components/ui/icons";
import { getCompetition } from "@/lib/data";
import { smsLink } from "@/lib/format";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Join",
  description: "Text JOIN with your name to enter the Brodie Push-Up Challenge. 18+, US, iPhone.",
};

const STEPS = [
  ["Text JOIN + your name", "Tap the button and send the pre-filled text. Add the name you want on the board after JOIN."],
  ["Confirm", "Reply to confirm you're 18+ and accept the rules."],
  ["Text QUEUE", "Get in line. We text you when it's your turn."],
  ["FaceTime and rep", "Call within 90 seconds and do strict push-ups on camera."],
] as const;

/** Illustrative Messages thread. Decorative: the steps below carry the same information. */
function MessagesMock() {
  const bubble = "max-w-[85%] rounded-3xl px-4 py-2.5 text-[0.9375rem] leading-snug";
  return (
    <div aria-hidden className="mx-auto w-full max-w-sm">
      <div className="rounded-[2.5rem] border border-hairline-strong bg-surface p-3 shadow-[0_40px_120px_-40px_rgb(212_255_58/0.35)]">
        <div className="rounded-[2rem] bg-canvas px-4 pt-4 pb-5">
          <div className="flex flex-col items-center gap-1 border-b border-hairline pb-3">
            <span className="grid size-10 place-items-center rounded-full bg-accent font-display text-lg font-extrabold text-on-accent">
              B
            </span>
            <span className="text-xs font-semibold text-ink-2">Brodie</span>
          </div>
          <div className="mt-4 flex flex-col gap-2">
            <p className={`${bubble} self-end rounded-br-md bg-accent font-semibold text-on-accent`}>JOIN Marcus T</p>
            <p className={`${bubble} self-start rounded-bl-md bg-surface-3 text-ink`}>
              Reply YES to confirm you&apos;re 18+, in the US, and agree to the rules.
            </p>
            <p className={`${bubble} self-end rounded-br-md bg-accent font-semibold text-on-accent`}>YES</p>
            <p className={`${bubble} self-end rounded-br-md bg-accent font-semibold text-on-accent`}>QUEUE</p>
            <p className={`${bubble} self-start rounded-bl-md bg-surface-3 text-ink`}>
              You&apos;re #2 in line, about 8 min. We&apos;ll text you when you&apos;re up.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default async function JoinPage() {
  const comp = await getCompetition();
  const link = smsLink(comp?.brodieNumber ?? null);
  const open = comp !== null;

  return (
    <div className="space-y-10 sm:space-y-14">
      <PageIntro
        eyebrow="Join the challenge"
        title="On the board in"
        accent="10 seconds."
        lede={
          <>
            One text gets you in. No app, no account, no password. Your phone number is{" "}
            <strong className="text-ink">never shown</strong>; only the name you pick is public.
          </>
        }
        art={<MessagesMock />}
      />

      <div className="card flex flex-col gap-4 border-accent/40 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
        {link ? (
          <>
            <p className="text-ink-2">
              Opens Messages with <strong className="font-mono text-ink">JOIN</strong> ready to go. Add your name and
              hit send.
            </p>
            <JoinButton href={link} size="lg" label="Text JOIN now" className="w-full shrink-0 sm:w-auto" />
          </>
        ) : (
          <p role="status" className="text-ink-2">
            {open
              ? "The sign-up number isn't published yet. Check back soon."
              : "Sign-up details are loading. Refresh in a moment."}
          </p>
        )}
      </div>

      <section aria-labelledby="steps" className="space-y-5">
        <SectionHeading id="steps" index="01">
          How it works
        </SectionHeading>
        <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map(([title, body], i) => (
            <li key={title} className="card relative overflow-hidden p-5">
              <span
                aria-hidden
                className="pointer-events-none absolute -top-3 -right-1 font-display text-8xl font-extrabold italic text-ink/5"
              >
                {i + 1}
              </span>
              <span className="font-mono text-sm font-bold text-accent">Step {i + 1}</span>
              <span className="mt-2 block font-display text-2xl font-extrabold uppercase leading-tight">{title}</span>
              <span className="mt-1 block text-sm leading-relaxed text-ink-2">{body}</span>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="who" className="grid gap-5 lg:grid-cols-[16rem_minmax(0,1fr)] lg:gap-10">
        <SectionHeading id="who" index="02">
          Who can play
        </SectionHeading>
        <div className="space-y-4">
          <ul className="flex flex-wrap gap-2">
            {["18 or older", "In the United States", "Have an iPhone (FaceTime)", "One person, one account"].map((t) => (
              <li
                key={t}
                className="inline-flex min-h-11 items-center gap-2 rounded-full border border-hairline-strong bg-surface px-4 text-sm font-semibold"
              >
                <CheckIcon className="size-4 text-accent" />
                {t}
              </li>
            ))}
          </ul>
          <Link href="/rules" className="inline-flex min-h-11 items-center gap-2 font-semibold text-accent hover:underline">
            Read the full rules <ArrowRightIcon className="size-4" />
          </Link>
        </div>
      </section>
    </div>
  );
}
