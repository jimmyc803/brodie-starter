import type { CoachStatus } from "@/lib/coach-view";

// Shown to coaches whose application (/start) isn't approved yet: what they can do now, and what unlocks on approval.
export function ReviewBanner({ status }: { status: CoachStatus }) {
  if (status === "approved") return null;
  if (status === "rejected")
    return (
      <section className="rounded-[14px] border border-line-strong bg-surface p-5">
        <h2 className="text-base font-semibold text-ink">We couldn&apos;t approve this account yet</h2>
        <p className="mt-1 text-sm text-ink-2">Brodie is in a small pilot with working coaches. Reply to our email if you think we got it wrong.</p>
      </section>
    );
  return (
    <section className="rounded-[14px] border border-line bg-warn-soft p-5">
      <h2 className="text-base font-semibold text-warn">Your coach application is in review</h2>
      <p className="mt-1 max-w-3xl text-sm text-ink-2">
        We look at every coach personally, usually within 24 hours. Meanwhile, explore the <b className="text-ink">demo client</b> and upload a
        program to see Brodie read it. Adding your own clients and sending workout links unlocks when you&apos;re approved.
      </p>
    </section>
  );
}
