import type { Metadata } from "next";
import Link from "next/link";
import { PageIntro } from "@/components/editorial";
import { Bullets, DocLinks, EFFECTIVE, Gist, P, Section, Toc } from "@/components/legal";

export const metadata: Metadata = {
  title: "Terms of Use",
  description: "Terms of use and messaging terms for the Brodie Push-Up Challenge website and text service.",
};

const TOC = [
  ["who", "Who we are"],
  ["use", "Using the service"],
  ["messaging", "Messaging terms"],
  ["content", "Content"],
  ["liability", "Liability"],
  ["law", "Law"],
] as const;

export default function TermsPage() {
  return (
    <div className="space-y-10 sm:space-y-14">
      <PageIntro
        eyebrow="Terms of use"
        title="The"
        accent="fine print."
        lede="Terms for using this website and Brodie's text and FaceTime line, including the messaging terms for texts."
      />

      <Gist
        items={[
          <>
            <strong>18+, US, iPhone</strong>, one account per person.
          </>,
          <>
            <strong>Texts:</strong> frequency varies, message and data rates may apply, STOP stops them, HELP helps.
          </>,
          <>
            <strong>Play fair.</strong> Cheating or abuse gets you removed.
          </>,
          <>
            <strong>Prizes and contest terms</strong> are in the <Link href="/rules" className="font-semibold underline">Official Rules</Link>, which win if there is a conflict.
          </>,
        ]}
        note={<>Effective {EFFECTIVE}.</>}
      />

      <Toc items={TOC} />

      <Section id="who" index="01" title="Who we are">
        <P>
          This website, the Brodie text number and the FaceTime line (the &ldquo;Service&rdquo;) are run by <strong>Beat Muse</strong>, a
          student project at the <strong>University of Pennsylvania</strong> (&ldquo;we&rdquo;). The University of Pennsylvania does not
          operate or endorse the Service. By using the Service you agree to these terms, the{" "}
          <Link href="/rules" className="font-semibold text-accent underline">Official Rules</Link> and the{" "}
          <Link href="/privacy" className="font-semibold text-accent underline">Privacy Policy</Link>.
        </P>
      </Section>

      <Section id="use" index="02" title="Using the service">
        <Bullets
          items={[
            "You must be 18 or older and in the United States, and you may have one account.",
            "Give true information, keep your display name free of profanity, slurs and impersonation, and don't use someone else's phone.",
            "Don't try to fool the judge, break the queue, overload or probe the Service, or interfere with other people's turns.",
            "Don't scrape private data. The leaderboard is public to view; the rest isn't.",
            "We may refuse, pause or end your access, rename you, or remove your scores if you break these terms or the rules.",
            "The Service may be down, late or wrong. We don't promise it is always available or that every rep is counted correctly.",
            "Push-ups are strenuous. You use the Service at your own risk and are responsible for your own safety.",
          ]}
        />
      </Section>

      <Section id="messaging" index="03" title="Messaging terms">
        <Bullets
          items={[
            <>
              <strong>Program:</strong> Brodie Push-Up Challenge texts, sent by Beat Muse through iMessage on Brodie&apos;s number.
            </>,
            <>
              <strong>Consent:</strong> when you text JOIN and reply YES you agree to receive texts about the Challenge, including replies to your commands, queue and &ldquo;you&apos;re up&rdquo; texts, call results, power hour alerts, rank-drop alerts, a daily recap at 10 AM ET, a streak reminder in the evening, an ending-soon notice and final results. Consent is not a condition of any purchase, and nothing is sold.
            </>,
            <>
              <strong>Frequency:</strong> varies with how much you play, usually a few texts on the days you take part. Rank-drop texts are limited to one every few hours. Outside replies, &ldquo;you&apos;re up&rdquo; texts and call results, Brodie sends nothing between 11 PM and 9 AM ET.
            </>,
            <>
              <strong>Cost:</strong> we don&apos;t charge for texts. Your carrier&apos;s message and data rates may apply.
            </>,
            <>
              <strong>STOP:</strong> text STOP (also QUIT, CANCEL, UNSUBSCRIBE or END) any time to stop proactive texts and leave the queue. Brodie confirms once. Text START to turn them back on; texting QUEUE also opts you back in.
            </>,
            <>
              <strong>HELP:</strong> text HELP for the command list (JOIN, YES, QUEUE, STATUS, TOP, LEAVE, RULES, POWER, STOP, START). To reach a person, reply to any message from Brodie.
            </>,
            "Carriers and Apple are not liable for delayed or undelivered messages. We don't share or sell your phone number for marketing; see the Privacy Policy.",
          ]}
        />
      </Section>

      <Section id="content" index="04" title="Content and ownership">
        <P>
          The site design, Brodie character, text and software belong to us or our licensors. You may view and share the public pages.
          You give us the right to show your display name, scores and result cards in the Service and in posts about the Challenge.
          No video or audio of you is stored, so none can be reused.
        </P>
      </Section>

      <Section id="liability" index="05" title="Disclaimers and liability">
        <Bullets
          items={[
            "The Service is provided as is and as available, without warranties of any kind, to the fullest extent the law allows.",
            "We are not liable for indirect, incidental or consequential damages, or for injury, lost data, lost messages, or loss caused by technical failures or by third-party services such as your phone carrier, Apple, or our providers.",
            "Our total liability for any claim about the Service is limited to $100, or the value of the prize in dispute if that is higher. This doesn't limit liability that can't be limited by law.",
            "You release us and the University of Pennsylvania from claims about your use of the Service to the fullest extent allowed by law.",
          ]}
        />
      </Section>

      <Section id="law" index="06" title="Changes and governing law">
        <P>
          We may change these terms by posting a new version here; using the Service afterwards means you accept it. They are governed by
          the laws of the Commonwealth of Pennsylvania, and disputes go to the state or federal courts located in Pennsylvania. Void where
          prohibited. Questions: text HELP or reply to Brodie.
        </P>
        <DocLinks current="/terms" />
      </Section>
    </div>
  );
}
