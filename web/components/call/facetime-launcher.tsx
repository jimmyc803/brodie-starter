"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

// "Start workout" on a FaceTime line: reserve a free line for this client (POST /api/line/<token>), then FaceTime it.
// The worker on that line matches the call to the reservation, so the workout loads this client's day and saves to them.
type State =
  | { kind: "idle" }
  | { kind: "claiming" }
  | { kind: "ready"; handle: string; facetime: string; expiresAt: number }
  | { kind: "busy"; nextFreeAt: number | null }
  | { kind: "error"; message: string };

const RETRY_MS = 15_000;

export function FaceTimeLauncher({ token }: { token: string }) {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "idle" });
  const [now, setNow] = useState(0);

  // Coming back from FaceTime: show the new recap.
  useEffect(() => {
    const onShow = () => {
      if (document.visibilityState === "visible") router.refresh();
    };
    document.addEventListener("visibilitychange", onShow);
    return () => document.removeEventListener("visibilitychange", onShow);
  }, [router]);

  // Countdown while a line is held; retry while every line is busy.
  useEffect(() => {
    if (state.kind !== "ready" && state.kind !== "busy") return;
    const tick = setInterval(() => setNow(Date.now()), 1000);
    const retry = state.kind === "busy" ? setTimeout(() => void claim(), RETRY_MS) : undefined;
    return () => {
      clearInterval(tick);
      clearTimeout(retry);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  async function claim() {
    setState((s) => (s.kind === "busy" ? s : { kind: "claiming" }));
    try {
      const res = await fetch(`/api/line/${encodeURIComponent(token)}`, { method: "POST" });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ?? "Could not start your workout.");
      setNow(Date.now());
      if (body.ok) setState({ kind: "ready", handle: body.handle, facetime: body.facetime, expiresAt: Date.parse(body.expiresAt) });
      else setState({ kind: "busy", nextFreeAt: body.nextFreeAt ? Date.parse(body.nextFreeAt) : null });
    } catch (e) {
      setState({ kind: "error", message: e instanceof Error ? e.message : "Could not start your workout." });
    }
  }

  if (state.kind === "ready") {
    const left = Math.max(0, Math.round((state.expiresAt - now) / 1000));
    if (left === 0)
      return (
        <div>
          <p className="text-sm text-ink-2">Your line was released. Tap again when you&apos;re ready.</p>
          <StartButton onClick={claim} label="Start workout" />
        </div>
      );
    return (
      <div>
        <a
          href={state.facetime}
          className="block w-full rounded-[14px] bg-brand px-6 py-4 text-center text-lg font-semibold text-on-brand transition hover:brightness-95"
        >
          FaceTime Brodie
        </a>
        <p className="mt-3 text-center text-sm text-ink-2">
          Your line is held for{" "}
          <span className="tabular-nums text-ink">
            {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}
          </span>
          . Video call <span className="whitespace-nowrap text-ink">{state.handle}</span>.
        </p>
      </div>
    );
  }

  if (state.kind === "busy") {
    const wait = state.nextFreeAt ? Math.max(1, Math.ceil((state.nextFreeAt - (now || Date.now())) / 60_000)) : null;
    return (
      <div className="rounded-[14px] bg-warn-soft p-4">
        <p className="font-semibold text-warn">Brodie is with someone right now</p>
        <p className="mt-1 text-sm text-ink-2">
          {wait ? `A line should free up in about ${wait} min.` : "A line should free up soon."} Keep this page open; it checks again
          on its own.
        </p>
      </div>
    );
  }

  return (
    <div>
      <StartButton onClick={claim} label={state.kind === "claiming" ? "Getting your line…" : "Start workout"} disabled={state.kind === "claiming"} />
      {state.kind === "error" ? (
        <p role="alert" className="mt-3 text-sm text-bad">
          {state.message}
        </p>
      ) : null}
    </div>
  );
}

function StartButton({ onClick, label, disabled }: { onClick: () => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="mt-2 w-full rounded-[14px] bg-brand px-6 py-4 text-lg font-semibold text-on-brand transition hover:brightness-95 disabled:opacity-60"
    >
      {label}
    </button>
  );
}
