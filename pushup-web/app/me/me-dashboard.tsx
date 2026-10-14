"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useActionState, useCallback, useEffect, useRef, useState } from "react";
import type { RealtimeChannel, SupabaseClient } from "@supabase/supabase-js";
import { FlameIcon, PhoneIcon, ArrowRightIcon } from "@/components/ui/icons";
import { createMaxWaitDebounce } from "@/lib/throttle";
import {
  ME_IDLE,
  claimSecondsLeft,
  facetimeLink,
  formatClock,
  formatEtaRange,
  linkSmsHref,
  mePhase,
  ordinalRank,
  type Me,
  type MeActionState,
  type RegisteredMe,
} from "@/lib/me-view";
import { claimHandle, queueAction, setTexts } from "./actions";

const POLL_MS = 3_000;

type Snapshot = { me: RegisteredMe; at: number; seq: number };

/**
 * Live /me: polls /me/status every 3 s (paused while the tab is hidden), refetches on every site_pulse realtime event,
 * and ticks the "you're up" countdown locally between snapshots. Responses are applied in request order, so a slow
 * poll can never overwrite a newer action result.
 */
function useLiveMe(initial: RegisteredMe) {
  const router = useRouter();
  const seq = useRef(0);
  const [snap, setSnap] = useState<Snapshot>(() => ({ me: initial, at: Date.now(), seq: 0 }));

  const apply = useCallback((me: Me | undefined, id: number) => {
    if (!me) return;
    if (!me.registered) {
      router.refresh();
      return;
    }
    setSnap((prev) => (id < prev.seq ? prev : { me, at: Date.now(), seq: id }));
  }, [router]);

  const refetch = useCallback(async () => {
    const id = ++seq.current;
    try {
      const res = await fetch("/me/status", { cache: "no-store", headers: { Accept: "application/json" } });
      if (res.status === 401) {
        router.push("/login");
        return;
      }
      if (!res.ok) return; // transient: keep the last snapshot, the next poll retries
      apply((await res.json()) as Me, id);
    } catch {
      // offline: keep the last snapshot
    }
  }, [apply, router]);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;
    const start = () => {
      if (timer === undefined) timer = setInterval(() => void refetch(), POLL_MS);
    };
    const stop = () => {
      if (timer !== undefined) clearInterval(timer);
      timer = undefined;
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        void refetch();
        start();
      } else stop();
    };
    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);

    const pulse = createMaxWaitDebounce(() => void refetch(), 300, 800);
    let disposed = false;
    let sb: SupabaseClient | null = null;
    let channel: RealtimeChannel | undefined;
    void import("@/lib/supabase-browser")
      .then(({ getBrowserClient }) => {
        if (disposed) return;
        sb = getBrowserClient();
        channel = sb
          ?.channel("me_site_pulse")
          .on("postgres_changes", { event: "*", schema: "public", table: "site_pulse" }, pulse.trigger)
          .subscribe();
      })
      .catch((err: unknown) => console.error("live updates unavailable", err));

    return () => {
      disposed = true;
      stop();
      pulse.cancel();
      document.removeEventListener("visibilitychange", onVisibility);
      if (sb && channel) void sb.removeChannel(channel);
    };
  }, [refetch]);

  const fromAction = useCallback((state: MeActionState) => apply(state.me, ++seq.current), [apply]);
  return { snap, fromAction };
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

/** Run a server action and push its fresh status into the live snapshot. */
function useMeAction(action: (prev: MeActionState, fd: FormData) => Promise<MeActionState>, onResult: (s: MeActionState) => void) {
  return useActionState(async (prev: MeActionState, fd: FormData) => {
    const next = await action(prev, fd);
    onResult(next);
    return next;
  }, ME_IDLE);
}

export function MeDashboard({ initial }: { initial: RegisteredMe }) {
  const { snap, fromAction } = useLiveMe(initial);
  const me = snap.me;
  const phase = mePhase(me);
  const now = useNow(phase === "up");
  const secondsLeft = me.claim ? claimSecondsLeft(me.claim.seconds_left, snap.at, now) : 0;
  const ft = facetimeLink(me.brodie_number);
  const [qState, qAction, qPending] = useMeAction(queueAction, fromAction);
  const [tState, tAction, tPending] = useMeAction(setTexts, fromAction);
  const inLine = me.queue.status === "waiting" || me.queue.status === "notified" || phase === "up";
  const cap = me.daily_call_cap ?? me.calls_today + me.calls_left;

  return (
    <div className="space-y-5">
      <header className="flex items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="eyebrow">Signed in</p>
          <h1 className="truncate font-display text-4xl font-extrabold uppercase italic leading-none sm:text-5xl">
            {me.display_name}
          </h1>
        </div>
        <Link
          href={`/u/${encodeURIComponent(me.display_name)}`}
          className="inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-full border border-hairline-strong px-4 text-sm font-semibold text-ink-2 hover:border-accent hover:text-ink"
        >
          Profile <ArrowRightIcon className="size-4" />
        </Link>
      </header>

      <StatusHero me={me} phase={phase} secondsLeft={secondsLeft} facetime={ft} />

      {me.handle ? null : <VerifyCard me={me} onResult={fromAction} />}

      <dl className="grid grid-cols-2 gap-3">
        <Stat label="Today's points" value={String(me.points_today)} accent />
        {me.uncapped ? (
          <Stat label="Calls left today" value="No cap" hint={`${me.calls_today} today · team · first in line`} />
        ) : (
          <Stat label="Calls left today" value={`${me.calls_left}`} hint={`of ${cap} · resets midnight ET`} />
        )}
        <Stat label="Total points" value={String(me.points)} hint={me.rank ? `${ordinalRank(me.rank)} of ${me.total_users}` : "Unranked"} />
        <Stat
          label="Day streak"
          value={String(me.streak)}
          hint={`${me.valid_reps} valid reps`}
          icon={me.streak > 0 ? <FlameIcon className="size-5 text-gold" /> : null}
        />
      </dl>

      <form action={tAction} className="card flex items-center justify-between gap-4 p-4">
        <input type="hidden" name="opted_out" value={me.opted_out ? "0" : "1"} />
        <div className="min-w-0">
          <p className="font-semibold">Brodie texts</p>
          <p className="text-sm text-ink-3">
            {me.opted_out ? "Off (STOP). Turning on is like texting START." : "On. Turning off is like texting STOP and leaves the line."}
          </p>
          {tState.status && !tState.ok ? <p role="alert" className="mt-1 text-sm text-bad">{tState.error}</p> : null}
        </div>
        <button
          type="submit"
          role="switch"
          aria-checked={!me.opted_out}
          aria-label="Brodie texts"
          disabled={tPending}
          className={`relative h-8 w-14 shrink-0 rounded-full border transition-colors disabled:opacity-60 ${me.opted_out ? "border-hairline-strong bg-surface-3" : "border-accent bg-accent"}`}
        >
          <span
            aria-hidden
            className={`absolute top-1/2 size-6 -translate-y-1/2 rounded-full transition-[left] duration-200 ${me.opted_out ? "left-0.5 bg-ink-3" : "left-[1.625rem] bg-on-accent"}`}
          />
        </button>
      </form>

      {me.ref_code ? <InviteCard code={me.ref_code} /> : null}

      {/* Thumb-reach queue control: sticky on phones, inline on larger screens. */}
      <form
        action={qAction}
        className="sticky bottom-0 z-20 -mx-4 bg-gradient-to-t from-canvas via-canvas/95 to-transparent px-4 pt-6 pb-[max(1rem,env(safe-area-inset-bottom))] sm:static sm:mx-0 sm:bg-none sm:p-0"
      >
        <input type="hidden" name="action" value={inLine ? "leave" : "join"} />
        <QueueButton phase={phase} inLine={inLine} pending={qPending} />
        <p role="status" aria-live="polite" className={`mt-2 min-h-5 text-center text-sm ${qState.ok ? "text-ink-2" : "text-bad"}`}>
          {qState.status ? (qState.ok ? qState.message : qState.error) : null}
        </p>
      </form>
    </div>
  );
}

function QueueButton({ phase, inLine, pending }: { phase: ReturnType<typeof mePhase>; inLine: boolean; pending: boolean }) {
  const blocked = phase === "in_call" || phase === "at_cap" || phase === "closed" || phase === "banned";
  if (inLine) {
    return (
      <button
        type="submit"
        disabled={pending}
        className="inline-flex min-h-14 w-full items-center justify-center rounded-[var(--radius-card)] border-2 border-ink bg-surface-2 px-6 font-display text-xl uppercase tracking-wide text-ink transition-transform active:scale-[0.98] disabled:opacity-60"
      >
        {pending ? "Leaving…" : "Leave the line"}
      </button>
    );
  }
  return (
    <button
      type="submit"
      disabled={pending || blocked}
      className="inline-flex min-h-14 w-full items-center justify-center press rounded-[var(--radius-card)] border-2 border-ink bg-pink px-6 font-display text-xl uppercase tracking-wide text-ink transition-transform active:scale-[0.98] disabled:bg-surface-3 disabled:text-ink-3 disabled:shadow-none"
    >
      {pending ? "Joining…" : blocked ? "Line closed for you" : "Get in line"}
    </button>
  );
}

function StatusHero({
  me,
  phase,
  secondsLeft,
  facetime,
}: {
  me: RegisteredMe;
  phase: ReturnType<typeof mePhase>;
  secondsLeft: number;
  facetime: string | null;
}) {
  if (phase === "up") {
    return (
      <section
        aria-live="assertive"
        className="relative overflow-hidden card bg-pink p-5 text-ink stripes-live animate-stripes sm:p-6"
      >
        <p className="eyebrow text-ink">You&apos;re up</p>
        <p className="mt-1 font-display text-hero font-extrabold uppercase italic leading-none">FaceTime now</p>
        <p className="mt-3 font-mono text-6xl font-bold tabular-nums" aria-label={`${secondsLeft} seconds left`}>
          {formatClock(secondsLeft)}
        </p>
        <p className="mt-1 text-sm font-semibold">Call before the clock hits zero or the spot goes to the next person.</p>
        {facetime ? (
          <a
            href={facetime}
            className="mt-4 inline-flex min-h-14 w-full items-center justify-center gap-2 press rounded-[var(--radius-card)] border-2 border-ink bg-ink px-6 font-display text-xl uppercase tracking-wide text-canvas"
          >
            <PhoneIcon className="size-5" /> FaceTime Brodie
          </a>
        ) : null}
      </section>
    );
  }
  const card = (eyebrow: string, title: React.ReactNode, body: React.ReactNode, tone = "") => (
    <section aria-live="polite" className={`card p-5 sm:p-6 ${tone}`}>
      <p className="eyebrow">{eyebrow}</p>
      <div className="mt-1 font-display text-hero font-extrabold uppercase italic leading-none">{title}</div>
      <div className="mt-3 text-ink-2">{body}</div>
    </section>
  );
  switch (phase) {
    case "in_call":
      return card(
        "Live",
        <span className="text-live">On the line</span>,
        "Rep it out: 3:00 to count, then Brodie hangs up at 3:15. Results land here when the call ends.",
        "border-live/40",
      );
    case "waiting": {
      const eta = formatEtaRange(me.queue.eta);
      return card(
        "In line",
        <>
          <span className="overprint">#{me.queue.position ?? "…"}</span>
          <span className="ml-3 text-3xl text-ink-2 not-italic">in line</span>
        </>,
        <>
          {eta ? (
            <>
              Your turn in <strong className="text-ink">{eta}</strong>.{" "}
            </>
          ) : null}
          Keep this page open: it flips to a countdown when you&apos;re up. Fewest calls today goes first.
        </>,
        "border-accent/40",
      );
    }
    case "open":
      return card(
        "Line's open",
        <span className="text-accent">Walk right in</span>,
        <>
          Nobody&apos;s waiting. {facetime ? (
            <a href={facetime} className="font-semibold text-ink underline underline-offset-4">FaceTime Brodie now</a>
          ) : "FaceTime Brodie now"}{" "}
          or get in line to hold a spot.
        </>,
        "border-accent/40",
      );
    case "at_cap":
      return card("Done for today", "Maxed out", "You've used today's calls. Your next one unlocks at midnight ET.");
    case "closed":
      return card(
        me.frozen ? "Final" : "Not started",
        me.frozen ? "Board frozen" : "Soon",
        me.frozen ? "Scoring is closed. Final results are pending verification." : "The line opens when the competition starts.",
      );
    case "banned":
      return card("Account", "Can't queue", "This account can't join the line. Contact the team if this is a mistake.", "border-bad/40");
    default:
      return card("Not in line", "Ready?", "Get in line and we'll count you down here when it's your turn.");
  }
}

/** The user's invite link. Friends who text JOIN from it are credited to this account (no contact details shared). */
function InviteCard({ code }: { code: string }) {
  const path = `/join?ref=${encodeURIComponent(code)}`;
  const [note, setNote] = useState<string | null>(null);
  const share = async () => {
    const url = new URL(path, window.location.origin).toString();
    try {
      if (typeof navigator.share === "function") {
        await navigator.share({ title: "Brodie Push-Up Challenge", text: "Push-up battle on FaceTime. Join me:", url });
        return;
      }
      await navigator.clipboard.writeText(url);
      setNote("Link copied.");
    } catch (e) {
      // A dismissed share sheet is not an error; anything else falls back to showing the link to copy by hand.
      if (e instanceof DOMException && e.name === "AbortError") return;
      setNote(url);
    }
  };
  return (
    <section aria-labelledby="invite-heading" className="card flex items-center justify-between gap-4 p-4">
      <div className="min-w-0">
        <p id="invite-heading" className="font-semibold">Invite friends</p>
        <p className="text-sm text-ink-3">
          Your code <strong className="font-mono text-ink">{code}</strong> rides along when they text JOIN from your link.
        </p>
        {note ? <p role="status" className="mt-1 text-sm break-all text-ink-2">{note}</p> : null}
      </div>
      <button
        type="button"
        onClick={share}
        className="min-h-11 shrink-0 rounded-full border border-hairline-strong px-4 text-sm font-semibold hover:border-accent hover:text-accent"
      >
        Share link
      </button>
    </section>
  );
}

function Stat({ label, value, hint, accent, icon }: { label: string; value: string; hint?: string; accent?: boolean; icon?: React.ReactNode }) {
  return (
    <div className="card p-4">
      <dt className="text-sm font-semibold text-ink-2">{label}</dt>
      <dd className={`mt-1 flex items-center gap-1.5 font-display text-5xl font-extrabold leading-none tabular-nums ${accent ? "text-accent" : "text-ink"}`}>
        {value}
        {icon}
      </dd>
      {hint ? <dd className="mt-1 text-xs text-ink-3">{hint}</dd> : null}
    </div>
  );
}

/**
 * D-25: the FaceTime handle only counts once its owner proves it by texting LINK <code> from it. Until then the user
 * gets no texts and is recognised on calls by the claim window only.
 */
function VerifyCard({ me, onResult }: { me: RegisteredMe; onResult: (s: MeActionState) => void }) {
  const [state, action, pending] = useMeAction(claimHandle, onResult);
  const [copied, setCopied] = useState(false);
  const claim = me.pending_claim && !me.pending_claim.expired ? me.pending_claim : null;
  const sms = claim ? linkSmsHref(me.brodie_number, claim.code) : null;

  const copy = async () => {
    if (!claim) return;
    try {
      await navigator.clipboard.writeText(`LINK ${claim.code}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <section aria-labelledby="verify-heading" className="card border-gold/40 p-5">
      <p id="verify-heading" className="eyebrow text-gold">
        Verify your number
      </p>
      {claim ? (
        <>
          <p className="mt-2 text-lg">
            Text <strong className="font-mono text-ink">LINK {claim.code}</strong> to{" "}
            {me.brodie_number ? <strong className="whitespace-nowrap text-ink">{me.brodie_number}</strong> : "Brodie"} from{" "}
            <strong className="whitespace-nowrap text-ink">{claim.handle}</strong>.
          </p>
          <div className="mt-4 grid grid-cols-2 gap-2">
            {sms ? (
              <a
                href={sms}
                className="inline-flex min-h-12 items-center justify-center press rounded-[var(--radius-card)] border-2 border-ink bg-pink px-4 font-display text-lg uppercase tracking-wide text-ink"
              >
                Open Messages
              </a>
            ) : null}
            <button
              type="button"
              onClick={() => void copy()}
              className={`inline-flex min-h-12 items-center justify-center rounded-full border border-hairline-strong px-4 font-semibold text-ink ${sms ? "" : "col-span-2"}`}
            >
              <span aria-live="polite">{copied ? "Copied" : `Copy LINK ${claim.code}`}</span>
            </button>
          </div>
          <p className="mt-3 text-sm text-ink-3">
            Code works for 24 hours. Until it&apos;s verified you get no texts, and we recognise your call by your turn
            in line. You can skip this and play web-only.
          </p>
        </>
      ) : (
        <p className="mt-2 text-ink-2">
          {me.pending_claim?.expired ? "Your code expired. " : ""}Add the number or Apple ID email you FaceTime from to
          get texts and caller ID. Optional: without it you play web-only.
        </p>
      )}
      <form action={action} className="mt-4 flex gap-2">
        <label htmlFor="verify-handle" className="sr-only">
          FaceTime number or Apple ID email
        </label>
        <input
          id="verify-handle"
          name="handle"
          required
          maxLength={254}
          autoComplete="tel"
          autoCapitalize="none"
          spellCheck={false}
          defaultValue={me.pending_claim?.handle ?? ""}
          placeholder="(555) 123-4567"
          className="min-h-12 min-w-0 flex-1 rounded-[var(--radius-card)] border-2 border-ink bg-surface px-4 text-ink placeholder:text-ink-3 focus:bg-canvas focus:outline-none"
        />
        <button
          type="submit"
          disabled={pending}
          className="min-h-12 shrink-0 rounded-full border border-hairline-strong px-4 text-sm font-semibold text-ink hover:border-accent disabled:opacity-60"
        >
          {pending ? "…" : claim ? "New code" : "Get code"}
        </button>
      </form>
      <p role="status" aria-live="polite" className={`mt-2 min-h-5 text-sm ${state.ok ? "text-ink-2" : "text-bad"}`}>
        {state.status ? (state.ok ? state.message : state.error) : null}
      </p>
    </section>
  );
}
