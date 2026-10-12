import { RepIllustrations } from "@/components/rep-illustrations";
import { getCompetition } from "@/lib/data";

export const dynamic = "force-dynamic";
export const metadata = { title: "Rules | Brodie Push-Up Challenge" };

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="font-display text-3xl uppercase text-accent">{title}</h2>
      {children}
    </section>
  );
}

export default async function RulesPage() {
  const comp = await getCompetition();
  const minReps = comp?.raffleMinValidReps ?? 100;
  const rafflePrize = comp?.rafflePrize ?? "TBD";

  return (
    <div className="space-y-8 leading-relaxed [&_ul]:list-disc [&_ul]:space-y-1 [&_ul]:pl-5">
      <h1 className="font-display text-5xl uppercase leading-none">Rules</h1>

      <Section title="Scoring">
        <ul>
          <li>Points = valid reps x multiplier. 1x normally, 2x during power hour.</li>
          <li>Points add up across the whole week. Rank is by points.</li>
          <li>Tie? Whoever reached the tied total first ranks higher.</li>
          <li>We show valid reps and points separately. Rejected reps are shown with the reason and score 0.</li>
        </ul>
      </Section>

      <Section title="The strict rep standard">
        <p>A rep counts only if it passes every check. When in doubt, it does not count.</p>
        <ul>
          <li>Whole body in frame from the side: shoulders, hips, knees, ankles.</li>
          <li>Only you in frame.</li>
          <li>Knees off the floor the entire rep.</li>
          <li>Straight line from shoulders to ankles. Sagging and piking both fail.</li>
          <li>Chest down until your elbows reach 90 degrees or lower.</li>
          <li>Full lockout at the top before the next rep.</li>
          <li>No rushing: each rep takes at least about 0.8 seconds.</li>
        </ul>
        <RepIllustrations />
        <p>
          Once per call you get a quick liveness challenge (for example, tap your left shoulder). Reps during
          the challenge do not count and are not penalized. Fail it twice and that call&apos;s reps are voided.
        </p>
      </Section>

      <Section title="Calls and the queue">
        <ul>
          <li>Each call lasts 3:15. You get 3:00 to do reps (set up inside it), then a 15 second reveal.</li>
          <li>Text QUEUE to get in line. Whoever has had the fewest counted calls today goes first; ties go first-come, first-served.</li>
          <li>When you are up you have 90 seconds to FaceTime in, or you lose your spot.</li>
          <li>If the line is empty and idle, you can walk right in.</li>
          <li>If it is not your turn, the call is ended and nothing is recorded.</li>
          <li>Alt accounts give no advantage: reps stay with the account that did them.</li>
        </ul>
      </Section>

      <Section title="Daily cap">
        <p>
          Up to 5 counted calls per person per day (Eastern Time). A call counts if you were connected for at
          least 30 seconds or did at least one rep. The cap resets at midnight ET.
        </p>
      </Section>

      <Section title="Power hour">
        <p>
          One power hour each day at a random time between 12:00 and 22:00 ET. Valid reps inside it score 2x,
          counted rep by rep. It is announced in the morning recap, 15 minutes before, and at the start.
        </p>
      </Section>

      <Section title="Prizes">
        <ul>
          <li>1st place: $100.</li>
          <li>Top 3: a group call with a UFC fighter.</li>
          <li>
            Raffle: everyone with at least {minReps} valid reps (reps, not points) is entered. Prize: {rafflePrize}.
            The draw is reproducible and logged.
          </li>
        </ul>
      </Section>

      <Section title="Eligibility">
        <ul>
          <li>18 or older, located in the US, with an iPhone.</li>
          <li>One person, one account.</li>
          <li>Texting JOIN confirms you are 18+ and accept these rules.</li>
        </ul>
      </Section>

      <Section title="Verification and the end">
        <ul>
          <li>The challenge ends Sunday, Oct 18, 2026 at 11:59:59 PM ET. Scoring freezes then; later reps do not count.</li>
          <li>After the freeze the board reads &ldquo;FINAL &mdash; pending verification&rdquo;.</li>
          <li>The top 3 do a live verification call before any payout.</li>
          <li>Admins can void calls or adjust scores. Every change needs a reason and is logged.</li>
        </ul>
      </Section>

      <Section title="Privacy">
        <p>
          No video or audio is stored. Only pose measurements for each rep are kept. Your phone number is
          never shown publicly; the site shows only your chosen display name.
        </p>
      </Section>
    </div>
  );
}
