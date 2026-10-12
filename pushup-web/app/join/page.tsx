import { getCompetition } from "@/lib/data";
import { smsLink } from "@/lib/format";

export const dynamic = "force-dynamic";
export const metadata = { title: "Join | Brodie Push-Up Challenge" };

export default async function JoinPage() {
  const comp = await getCompetition();
  const link = smsLink(comp?.brodieNumber ?? null);
  const open = comp !== null;

  return (
    <div className="space-y-6">
      <h1 className="font-display text-5xl uppercase leading-none">
        Join in <span className="text-accent">10 seconds</span>
      </h1>
      {link ? (
        <a
          href={link}
          className="block rounded-xl bg-accent px-5 py-5 text-center font-display text-2xl uppercase tracking-wide text-on-accent"
        >
          Text JOIN + your name
        </a>
      ) : (
        <p className="rounded-xl border border-hairline bg-surface p-4 text-ink-2">
          {open
            ? "The sign-up number is not published yet. Check back soon."
            : "Sign-up details are loading. Refresh in a moment."}
        </p>
      )}
      <section>
        <h2 className="font-display text-2xl uppercase text-accent">Steps</h2>
        <ol className="mt-2 list-decimal space-y-2 pl-5">
          <li>Tap the button and send the pre-filled text. Add the name you want on the board after JOIN.</li>
          <li>Reply to confirm you are 18+ and accept the rules.</li>
          <li>Text QUEUE to get in line. We text you when it is your turn.</li>
          <li>FaceTime the line within 90 seconds and do strict push-ups on camera.</li>
        </ol>
      </section>
      <section>
        <h2 className="font-display text-2xl uppercase text-accent">Who can play</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>You are 18 or older.</li>
          <li>You are in the United States.</li>
          <li>You have an iPhone (FaceTime is how you compete).</li>
          <li>One person, one account.</li>
        </ul>
      </section>
      <p className="text-sm text-ink-2">
        Your phone number is never shown on this site. Only the display name you choose is public.
      </p>
    </div>
  );
}
