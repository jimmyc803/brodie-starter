import type { Metadata } from "next";
import Link from "next/link";
import { CtaBand, PageIntro, StatTile } from "@/components/editorial";
import { RepIllustrations } from "@/components/rep-illustrations";
import { Bullets, DocLinks, EFFECTIVE, Gist, P, Section, Toc } from "@/components/legal";
import { CheckIcon } from "@/components/ui/icons";
import { getCompetition } from "@/lib/data";
import { formatEtDeadline, smsLink } from "@/lib/format";
import { ufcFighterCopy } from "@/lib/mappers";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Official Rules",
  description:
    "Official rules of the Brodie Push-Up Challenge: eligibility, entry period, how to play, what counts as a valid rep, scoring, prizes, privacy and more.",
};

const TOC = [
  ["sponsor", "Sponsor"],
  ["eligibility", "Eligibility"],
  ["period", "Entry period"],
  ["enter", "How to enter"],
  ["play", "How to play"],
  ["reps", "Valid reps"],
  ["scoring", "Scoring"],
  ["end", "The end"],
  ["prizes", "Prizes"],
  ["fair-play", "Fair play"],
  ["disputes", "Disputes"],
  ["privacy", "Privacy"],
  ["sms", "Texts"],
  ["publicity", "Publicity"],
  ["legal", "Legal"],
] as const;

export default async function RulesPage() {
  const comp = await getCompetition();
  const start = formatEtDeadline(comp?.windowStart ?? null) ?? "Mon Oct 12 · 8:00 PM ET";
  const end = formatEtDeadline(comp?.windowEnd ?? null) ?? "Tue Oct 20 · 11:59 PM ET";
  const prize = comp?.firstPrize ?? "$500";
  const drawingPrize = comp?.drawingPrize ?? "$500";
  const fighter = ufcFighterCopy(comp?.ufcFighter);

  return (
    <div className="space-y-10 sm:space-y-14">
      <PageIntro
        eyebrow="Official rules"
        title="Every rep"
        accent="earns it."
        lede="A rep counts only if it passes the judge. These are the complete rules of the Brodie Push-Up Challenge. By texting JOIN and replying YES you agree to them."
      />

      <Gist
        items={[
          <>
            <strong>Free to enter.</strong> No purchase necessary. 18+, US, iPhone, one account per person.
          </>,
          <>
            <strong>Text JOIN</strong> with a name, then <strong>YES</strong>, then <strong>QUEUE</strong> to get in line.
          </>,
          <>
            <strong>FaceTime Brodie</strong> when we text &ldquo;you&apos;re up&rdquo;. You get 3:00 to do strict push-ups on camera.
          </>,
          <>
            <strong>Valid reps = points.</strong> 2× in the daily power hour. Up to 5 counted calls a day.
          </>,
          <>
            <strong>Runs {start} to {end}.</strong> Then the board is &ldquo;FINAL, pending verification&rdquo;.
          </>,
          <>
            <strong>Top scorer wins {prize}, and {drawingPrize} goes to a random drawing</strong> where every valid rep is one
            ticket. Top 3 get a group call with {fighter}, after a verification call.
          </>,
          <>
            <strong>No video or audio is ever stored.</strong> The board shows display names only.
          </>,
          <>
            <strong>The judge&apos;s count and the admins&apos; decisions are final.</strong> Questions? Text HELP or reply to Brodie.
          </>,
        ]}
        note={<>Effective {EFFECTIVE}. The numbered sections below are the official rules; the box above is only a summary.</>}
      />

      <Toc items={TOC} />

      <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-4">
        <StatTile value="3:00" label="to rep, per call" hint="+15s reveal at the end" />
        <StatTile value="5" label="counted calls a day" hint="Resets midnight ET" />
        <StatTile value="2×" label="points in power hour" hint="One random hour daily" />
        <StatTile value="90s" label="to FaceTime in" hint="When we text you're up" />
      </div>

      <Section id="sponsor" index="01" title="Sponsor and no purchase">
        <P>
          The Brodie Push-Up Challenge (the &ldquo;Challenge&rdquo;) is sponsored and run by <strong>Beat Muse</strong>, a
          student project at the <strong>University of Pennsylvania</strong> (the &ldquo;Sponsor&rdquo;). The University of
          Pennsylvania does not sponsor, endorse or administer the Challenge.
        </P>
        <P>
          Chert, which provides the FaceTime and iMessage line, and Seraphim Labs appear on this site as supporters. They
          are not the Sponsor and do not run the Challenge or award prizes.
        </P>
        <P>
          <strong>NO PURCHASE OR PAYMENT OF ANY KIND IS NECESSARY TO ENTER OR WIN.</strong> Entering is free. Your mobile
          carrier may charge normal message and data rates. A purchase does not improve your chances.
        </P>
      </Section>

      <Section id="eligibility" index="02" title="Eligibility">
        <Bullets
          items={[
            "You must be 18 or older and located in the United States.",
            "You need an iPhone that can use FaceTime and iMessage.",
            "One person, one account. You may not enter more than once, and reps always stay with the account that did them, so a second account gives no advantage.",
            "Replying YES to Brodie confirms that you are 18+, in the US, and agree to these rules.",
            "The Challenge is void where prohibited by law, and you may not enter where participation would be unlawful.",
          ]}
        />
      </Section>

      <Section id="period" index="03" title="Entry period">
        <P>
          The Challenge starts <strong>{start}</strong> and ends <strong>{end}</strong> (all times are America/New_York,
          &ldquo;ET&rdquo;). Reps recorded outside that period do not score. A call that is still running when the period
          ends only scores the reps made before the end time. Days start and end at <strong>midnight ET</strong>.
        </P>
      </Section>

      <Section id="enter" index="04" title="How to enter">
        <P>
          Text <strong>JOIN</strong> followed by the display name you want on the board to Brodie&apos;s number (the
          &ldquo;Text JOIN&rdquo; button on this site opens the message for you). Example:{" "}
          <span className="font-mono text-ink">JOIN Marcus_T</span>.
        </P>
        <Bullets
          items={[
            "Display names are 3 to 20 characters: letters, numbers, underscores and single spaces. Names with profanity or slurs are refused, and names are unique.",
            "Brodie replies with a summary and asks you to reply YES. Your entry is complete when you reply YES. Joining means you accept these rules, the Terms and the Privacy Policy.",
            "You will then get a welcome text. You are on the public board after your first valid rep.",
          ]}
        />
        <P>
          Entries made by automated means, by anyone other than the person entering, or with false information are
          void.
        </P>
      </Section>

      <Section id="play" index="05" title="How to play">
        <Bullets
          items={[
            <>
              <strong>Queue.</strong> Brodie&apos;s line takes one caller at a time. Text <strong>QUEUE</strong> to get in line;
              Brodie texts your position and an estimated wait. The person with the fewest counted calls today goes first;
              ties go first-come, first-served.
            </>,
            <>
              <strong>Claim window.</strong> When it&apos;s your turn Brodie texts &ldquo;you&apos;re up&rdquo;. You have{" "}
              <strong>90 seconds</strong> to FaceTime Brodie, plus about 10 seconds of grace. If you miss it you lose your spot and can text QUEUE again.
              If the line is open when you text QUEUE, Brodie tells you to FaceTime right away.
            </>,
            <>
              <strong>The call.</strong> Each call lasts 3:15. You get <strong>3:00 to count</strong> (setting up happens
              inside that time), then a 15 second reveal of your result during which nothing more is counted. At 3:15 Brodie hangs up. Keep your camera on: if Brodie can&apos;t see you it says so and hangs up after about 20 seconds.
            </>,
            <>
              <strong>Your turn only.</strong> Only the person who was texted &ldquo;you&apos;re up&rdquo; can start a call. Any
              other call is ended quickly and nothing is recorded.
            </>,
            <>
              <strong>Daily cap.</strong> Up to <strong>5 counted calls</strong> per person per day. A call counts if you were
              connected for 30 seconds or more, or made at least one rep. A call on your turn that ends in under 30 seconds with no valid reps (for example someone else grabbed the line, or a dropped call) does not count, and you get your turn back once with a new &ldquo;you&apos;re up&rdquo; text. Calls an admin voids still count toward the cap. The
              cap resets at <strong>midnight ET</strong>. At the cap, Brodie won&apos;t queue you until it resets.
            </>,
            <>
              <strong>Between calls</strong> the line rests for a few minutes. You can text STATUS, TOP, POWER, LEAVE or RULES at
              any time. Full command list on <Link href="/how-it-works" className="font-semibold text-accent underline">How it works</Link>.
            </>,
          ]}
        />
      </Section>

      <Section id="reps" index="06" title="What counts as a valid rep">
        <P>
          The judge is automated. It watches your live video, measures your body and decides on every rep. A rep counts only if it
          passes all of these checks. Rejected reps score 0 and show the reason.
        </P>
        <ul className="grid gap-2 sm:grid-cols-2">
          {[
            "Your upper body and knees are in frame: shoulders, elbows and wrists visible. Your feet may be cut off.",
            "Only you are in frame.",
            "Real push-ups from your toes. Knee push-ups do not count, and your knees can't touch the floor.",
            "Your body stays roughly in one line. A small sag or pike is fine; a clearly sagging or piked-up body is not.",
            "Chest down until your elbows bend to about 90 to 125 degrees.",
            "Lock out at the top: arms nearly straight (about 130 degrees or more) before the next rep.",
            "Body roughly horizontal. A modest incline is fine; standing, wall or high-bench push-ups are not.",
            "No bouncing or rapid-fire half reps: each rep takes at least about half a second.",
          ].map((t) => (
            <li key={t} className="card-flat flex gap-3 px-4 py-3">
              <CheckIcon className="mt-0.5 size-4 shrink-0 text-blue" />
              <span className="text-sm leading-relaxed text-ink-2 sm:text-base">{t}</span>
            </li>
          ))}
        </ul>
        <RepIllustrations />
        <P>
          The judge is lenient on camera angle: front-on, side-on and diagonal all work &mdash; standing the phone in front of you is fine. Lay the phone sideways.
          Brodie coaches you live, saying the most useful fix first and not repeating the same cue within 10 seconds. It can still miss or misjudge a rep, and reps close to the line can go either way. Use the{" "}
          <Link href="/setup" className="font-semibold text-accent underline">setup guide</Link> to give it the best view. The
          judge&apos;s count is the official count.
        </P>
      </Section>

      <Section id="scoring" index="07" title="Scoring and power hour">
        <Bullets
          items={[
            <>
              <strong>Points = valid reps × multiplier.</strong> 1× normally, 2× during power hour. Points add up across the
              whole period, and rank is by total points. Valid reps and points are shown separately.
            </>,
            <>
              <strong>Power hour.</strong> Each day has one power hour at a random start between 12:00 and 22:00 ET. Valid reps
              made inside it score 2×, counted rep by rep. It is announced by text in the morning recap, 15 minutes before, and at the start (text POWER any
              time to see today&apos;s). Texts respect quiet hours, so check the site or text POWER if you didn&apos;t get one.
            </>,
            <>
              <strong>Tickets.</strong> Separately from points, each valid rep earns one ticket in the random drawing. Power hour
              does not double tickets: a 2× rep is still one ticket. Your ticket count equals your valid reps, shown on the board.
            </>,
            <>
              <strong>Ties.</strong> If two people have the same total, whoever reached that total first ranks higher.
            </>,
          ]}
        />
      </Section>

      <Section id="end" index="08" title="The end and verification">
        <Bullets
          items={[
            <>
              Scoring freezes at <strong>{end}</strong>. Reps after that do not count.
            </>,
            <>After the freeze the board reads &ldquo;FINAL, pending verification&rdquo;. Standings are not official until verification is done.</>,
            "The top 3 do a live verification call with the Sponsor before any prize is awarded: you show you are the person who earned the score, and the Sponsor may check your calls. A top-3 finisher who can't be reached, or doesn't complete verification within a reasonable time after being contacted, forfeits their place, and the next person in rank is verified instead.",
          ]}
        />
      </Section>

      <Section id="prizes" index="09" title="Prizes">
        <ul className="grid gap-2 sm:grid-cols-3">
          <li className="card bg-pink p-5">
            <p className="eyebrow text-ink">Top scorer</p>
            <p className="mt-2 font-display text-7xl leading-none">{prize}</p>
          </li>
          <li className="card bg-yellow p-5">
            <p className="eyebrow text-ink">Random drawing</p>
            <p className="mt-2 font-display text-7xl leading-none">{drawingPrize}</p>
          </li>
          <li className="card p-5">
            <p className="eyebrow">Top 3</p>
            <p className="mt-2 font-display text-3xl uppercase leading-tight">Group call with {fighter}</p>
          </li>
        </ul>
        <Bullets
          items={[
            `The top-scorer prize is ${prize} in US dollars, awarded to the entrant ranked 1st at the freeze, paid by the Sponsor once verification is complete. The winner provides the details needed to pay them and is responsible for any taxes.`,
            `The random-drawing prize is ${drawingPrize} in US dollars, awarded to one entrant drawn at random from all tickets after the freeze. Each valid rep is one ticket, so the more valid reps you make, the better your chance; power hour multiplies points, not tickets. An entrant with no valid reps holds no tickets and cannot be drawn.`,
            `The same entrant can win both cash prizes: being drawn does not remove you from the ranking, and ranking 1st does not remove your tickets from the drawing.`,
            `The drawing is run once, after the freeze and after verification, using a published method: tickets are laid out in order of entrant id and the winner is selected with a recorded random seed, so the Sponsor (or anyone given the seed) can recompute the same result. The seed and the ticket totals are kept with the final results record.`,
            `The group call is a video call between the top 3 verified finishers and ${fighter}. Its date depends on everyone's availability. If the named fighter becomes unavailable, the Sponsor may substitute another UFC fighter. It has no cash value.`,
            "No purchase or payment of any kind is required to enter or win, and no payment improves your chance of winning. Prizes are not transferable. There are no prizes other than those listed above.",
          ]}
        />
      </Section>

      <Section id="fair-play" index="10" title="Fair play, accounts and admin decisions">
        <Bullets
          items={[
            "Cheating isn't allowed: holding up pre-recorded or replayed video, filming a screen, having someone else do your reps, tricking the camera or the judge, using multiple accounts or phones to gain an advantage, harassing others, or abusing the service.",
            "The Sponsor may disqualify anyone who cheats or breaks these rules, remove their points, and withhold their prize.",
            "Admins may void a call, adjust a score, or ban an account, including after a re-check of stored rep measurements. A score adjustment moves your valid rep count by the same amount unless the admin corrects only the points. Every change needs a written reason and is recorded in an audit log.",
            "Because the judge is automated, the Sponsor may re-run stored rep measurements through a corrected version of the judge. Scores may change as a result.",
          ]}
        />
      </Section>

      <Section id="disputes" index="11" title="Decisions and disputes">
        <P>
          The judge&apos;s count, the leaderboard, and the Sponsor&apos;s decisions about rules, eligibility, scores and prizes are
          final. If you think something is wrong, text <strong>HELP</strong> or just reply to Brodie with what happened and
          roughly when. The team reads those messages and may review a call, correct a score, or explain the result. Reply
          timing is not guaranteed, and asking never guarantees a change.
        </P>
      </Section>

      <Section id="privacy" index="12" title="Privacy">
        <P>
          <strong>No video or audio is ever stored.</strong> Your call is processed live in memory; only rep counts and
          measurements, and a log of the cues Brodie said, are kept. The public board shows only your display name, never your
          phone number. The details are in the{" "}
          <Link href="/privacy" className="font-semibold text-accent underline">Privacy Policy</Link>.
        </P>
      </Section>

      <Section id="sms" index="13" title="Text messages, STOP and HELP">
        <Bullets
          items={[
            "By joining you agree to receive texts from Brodie about the Challenge: replies to your commands, queue and \"you're up\" messages, call results, power hour alerts, rank-drop alerts, a daily recap, reminders and final results. Message frequency varies. Message and data rates may apply. Consent isn't a condition of any purchase, but you need texts to play.",
            "Text STOP any time to stop proactive texts and leave the queue; Brodie always honors STOP. Text START to turn them back on. Text HELP for the command list. Text DELETE MY DATA to ask us to delete your account and data. Between 11 PM and 9 AM ET Brodie sends only replies to your commands, \"you're up\" texts and call results.",
            "Carriers are not liable for delayed or undelivered messages. See the Terms for the full messaging terms.",
          ]}
        />
        <P>
          <Link href="/terms#messaging" className="font-semibold text-accent underline">Messaging terms</Link>
        </P>
      </Section>

      <Section id="publicity" index="14" title="Publicity">
        <P>
          By entering you allow the Sponsor to show your display name, rank, points, rep counts and result cards on this site, in
          texts and in posts about the Challenge. Winners agree that the Sponsor may announce their display name and prize.
          Because no video or audio is stored, none can be published.
        </P>
      </Section>

      <Section id="legal" index="15" title="Risk, liability, changes and law">
        <Bullets
          items={[
            <>
              <strong>Your health and safety.</strong> Push-ups are strenuous. Only take part if you are healthy enough to do so, check with a doctor if unsure, clear space around you, and stop if you feel pain or dizziness. You take part at your own risk.
            </>,
            "Release. To the fullest extent the law allows, you release the Sponsor, its team members, its service providers, and the University of Pennsylvania from claims arising from the Challenge, including injury, loss, technical failures, lost or late texts or calls, miscounted reps, or errors on the board.",
            "Limitation. The Challenge and this site are provided as is. The Sponsor's total liability for any claim relating to the Challenge is limited to the value of the prize in question, and the Sponsor isn't liable for indirect or consequential damages. Nothing here limits liability that can't be limited by law.",
            "The Sponsor may pause, change or cancel the Challenge, or fix a bug, if fraud, a technical failure or something outside its control affects fairness or operation. The Sponsor may update these rules; changes are posted here with a new effective date, and rep decisions already made stay unless corrected under section 10.",
            "These rules are governed by the laws of the Commonwealth of Pennsylvania, without regard to its conflict-of-law rules. Disputes go to the state or federal courts located in Pennsylvania, and you consent to them. Void where prohibited.",
          ]}
        />
        <DocLinks current="/rules" />
      </Section>

      <CtaBand
        joinHref={smsLink(comp?.brodieNumber ?? null)}
        title="Think you're strict?"
        body="Text JOIN with your name. You'll be on the board after your first valid rep."
      />
    </div>
  );
}
