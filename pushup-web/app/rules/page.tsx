import type { Metadata } from "next";
import { CtaBand, PageIntro, SectionHeading, StatTile } from "@/components/editorial";
import { RepIllustrations } from "@/components/rep-illustrations";
import { CheckIcon } from "@/components/ui/icons";
import { getCompetition } from "@/lib/data";
import { formatEtDeadline, smsLink } from "@/lib/format";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Rules",
  description: "How strict push-ups are judged, scored and ranked in the Brodie Push-Up Challenge.",
};

const TOC = [
  ["scoring", "Scoring"],
  ["standard", "Rep standard"],
  ["calls", "Calls & queue"],
  ["power-hour", "Power hour"],
  ["prizes", "Prizes"],
  ["eligibility", "Eligibility"],
  ["verification", "The end"],
  ["privacy", "Privacy"],
] as const;

function Bullets({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="space-y-3">
      {items.map((item, i) => (
        <li key={i} className="flex gap-3 text-ink-2">
          <span aria-hidden className="mt-2 size-1.5 shrink-0 rounded-full bg-accent" />
          <span className="leading-relaxed">{item}</span>
        </li>
      ))}
    </ul>
  );
}

function Block({ id, index, title, children }: { id: string; index: string; title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="grid gap-4 border-t border-hairline pt-8 lg:grid-cols-[16rem_minmax(0,1fr)] lg:gap-10">
      <SectionHeading id={id} index={index}>
        {title}
      </SectionHeading>
      <div className="min-w-0 space-y-5">{children}</div>
    </section>
  );
}

export default async function RulesPage() {
  const comp = await getCompetition();
  const minReps = comp?.raffleMinValidReps ?? 100;
  const rafflePrize = comp?.rafflePrize ?? "TBD";
  const deadline = formatEtDeadline(comp?.windowEnd ?? null) ?? "Sun Oct 18 · 11:59 PM ET";

  return (
    <div className="space-y-10 sm:space-y-14">
      <PageIntro
        eyebrow="The rulebook"
        title="Every rep"
        accent="earns it."
        lede="A rep counts only if it passes every check. When in doubt, it does not count. Here is exactly what the judge looks for."
      />

      <nav aria-label="On this page" className="-mx-4 overflow-x-auto px-4 [scrollbar-width:none] sm:mx-0 sm:px-0">
        <ul className="flex w-max gap-2 sm:w-auto sm:flex-wrap">
          {TOC.map(([id, label]) => (
            <li key={id}>
              <a
                href={`#${id}`}
                className="inline-flex min-h-11 items-center rounded-full border border-hairline-strong bg-surface px-4 text-sm font-semibold whitespace-nowrap text-ink-2 transition-colors hover:border-accent hover:text-ink"
              >
                {label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
        <StatTile value="3:00" label="to rep, per call" hint="+15s reveal at the end" />
        <StatTile value="5" label="counted calls a day" hint="Resets midnight ET" />
        <StatTile value="2×" label="points in power hour" hint="One random hour daily" />
        <StatTile value="90s" label="to FaceTime in" hint="When we text you're up" />
      </div>

      <Block id="scoring" index="01" title="Scoring">
        <Bullets
          items={[
            <>
              <strong className="text-ink">Points = valid reps × multiplier.</strong> 1× normally, 2× during power hour.
            </>,
            "Points add up across the whole week. Rank is by points.",
            "Tie? Whoever reached the tied total first ranks higher.",
            "Valid reps and points are shown separately. Rejected reps show the reason and score 0.",
          ]}
        />
      </Block>

      <Block id="standard" index="02" title="The strict rep standard">
        <ul className="grid gap-2 sm:grid-cols-2">
          {[
            "Whole body in frame from the side: shoulders, hips, knees, ankles.",
            "Only you in frame.",
            "Knees off the floor the entire rep.",
            "Straight line from shoulders to ankles.",
            "Chest down until elbows hit 90° or lower.",
            "Full lockout at the top before the next rep.",
            "No rushing: each rep takes at least ~0.8 seconds.",
          ].map((t) => (
            <li key={t} className="flex gap-3 rounded-2xl border border-hairline bg-surface px-4 py-3">
              <CheckIcon className="mt-0.5 size-4 shrink-0 text-accent" />
              <span className="text-sm leading-relaxed text-ink-2 sm:text-base">{t}</span>
            </li>
          ))}
        </ul>
        <RepIllustrations />
        <p className="rounded-2xl border border-hairline bg-surface-2 px-4 py-3 text-sm leading-relaxed text-ink-2">
          <strong className="text-ink">Liveness check.</strong> Once per call you get a quick challenge (for example,
          tap your left shoulder). Reps during it do not count and are not penalized. Fail it twice and that
          call&apos;s reps are voided.
        </p>
      </Block>

      <Block id="calls" index="03" title="Calls and the queue">
        <Bullets
          items={[
            "Each call lasts 3:15. You get 3:00 to do reps (setup happens inside it), then a 15 second reveal.",
            "Text QUEUE to get in line. Fewest counted calls today goes first; ties are first-come, first-served.",
            "When you're up you have 90 seconds to FaceTime in, or you lose your spot.",
            "Line empty and idle? Walk right in.",
            "Not your turn? The call is ended and nothing is recorded.",
            "Alt accounts give no advantage: reps stay with the account that did them.",
            "Up to 5 counted calls per person per day (ET). A call counts if you were connected 30+ seconds or did at least one rep.",
          ]}
        />
      </Block>

      <Block id="power-hour" index="04" title="Power hour">
        <p className="leading-relaxed text-ink-2">
          One power hour each day at a random time between <strong className="text-ink">12:00 and 22:00 ET</strong>.
          Valid reps inside it score <strong className="text-accent">2×</strong>, counted rep by rep. It&apos;s
          announced in the morning recap, 15 minutes before, and at the start.
        </p>
      </Block>

      <Block id="prizes" index="05" title="Prizes">
        <ul className="grid gap-2 sm:grid-cols-3">
          <li className="card p-5">
            <p className="eyebrow">1st place</p>
            <p className="mt-2 font-display text-5xl font-extrabold text-accent">$100</p>
          </li>
          <li className="card p-5">
            <p className="eyebrow">Top 3</p>
            <p className="mt-2 font-display text-2xl font-extrabold uppercase leading-tight">Group call with a UFC fighter</p>
          </li>
          <li className="card p-5">
            <p className="eyebrow">Raffle · {minReps}+ valid reps</p>
            <p className="mt-2 font-display text-2xl font-extrabold uppercase leading-tight">{rafflePrize}</p>
            <p className="mt-1 text-sm text-ink-3">Reps, not points. Reproducible, logged draw.</p>
          </li>
        </ul>
      </Block>

      <Block id="eligibility" index="06" title="Eligibility">
        <Bullets
          items={[
            "18 or older, located in the US, with an iPhone.",
            "One person, one account.",
            "Texting JOIN confirms you are 18+ and accept these rules.",
          ]}
        />
      </Block>

      <Block id="verification" index="07" title="Verification and the end">
        <Bullets
          items={[
            <>
              The challenge ends <strong className="text-ink">{deadline}</strong>. Scoring freezes then; later reps
              do not count.
            </>,
            <>After the freeze the board reads &ldquo;FINAL, pending verification&rdquo;.</>,
            "The top 3 do a live verification call before any payout.",
            "Admins can void calls or adjust scores. Every change needs a reason and is logged.",
          ]}
        />
      </Block>

      <Block id="privacy" index="08" title="Privacy">
        <p className="leading-relaxed text-ink-2">
          No video or audio is stored. Only pose measurements for each rep are kept. Your phone number is never
          shown publicly; the site shows only the display name you choose.
        </p>
      </Block>

      <CtaBand
        joinHref={smsLink(comp?.brodieNumber ?? null)}
        title="Think you're strict?"
        body="Text JOIN with your name. You'll be on the board after your first valid rep."
      />
    </div>
  );
}
