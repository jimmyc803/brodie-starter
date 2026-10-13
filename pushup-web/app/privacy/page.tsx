import type { Metadata } from "next";
import Link from "next/link";
import { PageIntro } from "@/components/editorial";
import { Bullets, DocLinks, EFFECTIVE, Gist, P, Section, Toc } from "@/components/legal";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description:
    "What the Brodie Push-Up Challenge collects, what it never stores (no video or audio), how long it keeps data and how to delete it.",
};

const TOC = [
  ["collect", "What we collect"],
  ["never", "What we never store"],
  ["use", "How we use it"],
  ["public", "What is public"],
  ["share", "Who handles it"],
  ["keep", "How long we keep it"],
  ["delete", "Delete your data"],
  ["kids", "Age"],
  ["contact", "Contact"],
] as const;

export default function PrivacyPage() {
  return (
    <div className="space-y-10 sm:space-y-14">
      <PageIntro
        eyebrow="Privacy policy"
        title="No video."
        accent="No audio."
        lede="The judge watches you live and keeps the numbers, not the footage. This page explains exactly what is kept and for how long."
      />

      <Gist
        items={[
          <>
            <strong>Never stored:</strong> video or audio of you. Your call is processed live, in memory, and discarded.
          </>,
          <>
            <strong>Kept:</strong> your phone number or iMessage handle, display name, rep counts and measurements, call times and your messages with Brodie.
          </>,
          <>
            <strong>Public:</strong> only your display name, rank, points and reps. Never your phone number.
          </>,
          <>
            <strong>Deleted</strong> within 60 days after the Challenge ends, or sooner if you ask.
          </>,
        ]}
        note={<>Effective {EFFECTIVE}. This policy covers the Brodie Push-Up Challenge, run by Beat Muse, a student project at the University of Pennsylvania (&ldquo;we&rdquo;).</>}
      />

      <Toc items={TOC} />

      <Section id="collect" index="01" title="What we collect">
        <Bullets
          items={[
            <>
              <strong>Your contact handle.</strong> The phone number (or Apple ID) you text from. It is how Brodie recognizes you and replies. Chert, which runs the FaceTime line, shows us only a masked caller identity, so we match a call to you through the queue turn we gave you.
            </>,
            <>
              <strong>Your display name</strong> and when you confirmed you are 18+, in the US, and agree to the rules.
            </>,
            <>
              <strong>Rep data.</strong> For each call: the call time and length, how many reps were valid or rejected, the reject reasons, and body measurements for each rep such as joint angles and timing.
            </>,
            <>
              <strong>Cue logs.</strong> A log of the spoken prompts Brodie played during a call, for example &ldquo;lock those arms out&rdquo;.
            </>,
            <>
              <strong>Messages.</strong> Every text you send Brodie and every text Brodie sends you, with times and delivery status.
            </>,
            <>
              <strong>Queue and account state.</strong> Your queue entries, daily call counts, streaks, whether you opted out, and any admin action (void, adjustment, ban) with its reason.
            </>,
            <>
              <strong>Website data.</strong> If you use the optional website sign-in, your email address for the sign-in link. Our hosting provider also keeps ordinary request logs (IP address, browser, time). We use no advertising trackers.
            </>,
            <>
              <strong>Visit counts.</strong> The site counts visits and taps on its &ldquo;Text JOIN&rdquo; button. Each count stores only the time, the page, the referring website&apos;s domain and any link label or invite code in the link (like ?src=tiktok). No cookies, IP addresses or device identifiers, and nothing that ties a visit to you.
            </>,
            <>
              <strong>Invites.</strong> Every player gets an invite code. If you join with a friend&apos;s code (or from a labeled link), we record who invited you and how you found us. Our team sees this by display name only; it is never public.
            </>,
          ]}
        />
      </Section>

      <Section id="never" index="02" title="What we never store">
        <Bullets
          items={[
            <>
              <strong>No video and no audio.</strong> During your call, your video is analyzed by pose detection as it arrives, in the computer&apos;s memory, to find your body landmarks and count reps. The frames are not written to disk, saved to a database, or sent to storage, and nothing of the call is recorded.
            </>,
            "What we keep from a call is a log of rep counts, measurements and cues, not the video or the audio.",
            "The judge's skeleton overlay and rep stamps are drawn live on Brodie's side of the call and shown back to you. They are not saved.",
          ]}
        />
      </Section>

      <Section id="use" index="03" title="How we use it">
        <Bullets
          items={[
            "To run the Challenge: queue you, let you call, count and judge reps, score you, and rank the board.",
            "To text you: replies to your commands, queue and \"you're up\" texts, call results, power hour alerts, rank changes, a daily recap and reminders.",
            "To keep it fair: review disputes and suspected cheating, correct scores, and re-check stored rep measurements with a corrected judge.",
            "To keep it running: find and fix errors and abuse.",
            "To see how people find the Challenge: totals of visits, sign-ups and invites, for our team.",
            "To show results on the public leaderboard and result cards.",
            "We do not sell your data and we do not use it for ads.",
          ]}
        />
      </Section>

      <Section id="public" index="04" title="What is public">
        <P>
          The leaderboard, profile pages and result pages show your <strong>display name</strong>, rank, points, valid reps, streak
          and the per-call and per-day totals. They never show your phone number, handle, messages or email. Anyone with the
          link can view a result page, and display names can be searched, so pick a name you are happy to share. Do not use your
          real name or contact details as your display name if you want privacy.
        </P>
      </Section>

      <Section id="share" index="05" title="Who handles your data">
        <P>We use these service providers, only to run the Challenge:</P>
        <Bullets
          items={[
            <><strong>Chert</strong> provides the FaceTime line and the iMessage service, so it carries your calls and texts.</>,
            <><strong>LiveKit</strong> relays the live call between Chert and our judge.</>,
            <><strong>Amazon Web Services</strong> hosts the judge and the Challenge&apos;s server in the US. Video is analyzed there, in memory.</>,
            <><strong>Supabase</strong> hosts the database that stores the data in section 1.</>,
            <><strong>Vercel</strong> hosts this website.</>,
            <><strong>Google (Gemini)</strong> is used only to generate Brodie&apos;s fixed prompts as audio in advance. No participant video, audio, messages or data are sent to it.</>,
          ]}
        />
        <P>
          We may also share information when the law requires it, to protect people from harm or fraud, or to enforce the rules.
          Winners&apos; display names and prize results may be announced.
        </P>
      </Section>

      <Section id="keep" index="06" title="How long we keep it">
        <Bullets
          items={[
            "While the Challenge runs, we keep your data so the game works.",
            "Within 60 days after the Challenge ends (by December 17, 2026), we delete or anonymize personal data: your handle, messages, email, and call and rep records tied to you. Backups roll off on their own schedule.",
            "We may keep a final results record (display name, final rank and points) and an audit log of admin actions longer, to settle disputes and pay prizes. Prize winners' payment details are kept only as needed to pay and for tax and legal records.",
            "Test accounts and calls made before launch are removed before the public launch.",
          ]}
        />
      </Section>

      <Section id="delete" index="07" title="Delete your data or stop texts">
        <Bullets
          items={[
            <>
              <strong>Stop texts:</strong> text <strong>STOP</strong>. Brodie stops proactive texts and removes you from the queue right away. STOP does not delete your data; text START or QUEUE to come back.
            </>,
            <>
              <strong>Delete your data:</strong> text Brodie &ldquo;delete my data&rdquo; from the number you joined with. A team member will remove or anonymize your personal data and take you off the board, normally within 30 days. This ends your participation and any prize claim.
            </>,
            "Ask the same way for a copy of what we hold about you or to correct it.",
          ]}
        />
      </Section>

      <Section id="kids" index="08" title="Age and security">
        <P>
          The Challenge is for people <strong>18 and older</strong>. We do not knowingly collect data from anyone under 18. If we find an account that belongs to someone younger, we delete it.
        </P>
        <P>
          We limit access to the database to the team, use encrypted connections, keep secret keys off the website, and show the public
          site only through views that leave out phone numbers. No system is perfectly secure, and we cannot promise it.
        </P>
      </Section>

      <Section id="contact" index="09" title="Contact and changes">
        <P>
          Reach us by texting Brodie&apos;s number (text <strong>HELP</strong> or just reply to a message). We read those messages. We may
          update this policy; the effective date at the top changes when we do. See also the{" "}
          <Link href="/terms" className="font-semibold text-accent underline">Terms</Link> and{" "}
          <Link href="/rules" className="font-semibold text-accent underline">Official Rules</Link>.
        </P>
        <DocLinks current="/privacy" />
      </Section>
    </div>
  );
}
