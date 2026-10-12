"use client";

import { useState, useSyncExternalStore } from "react";

const noop = () => () => {};

// The client's personal workout link with Copy / Text / Share, so the coach can send it straight from the dashboard.
export function ClientLink({ code, name, coachName }: { code: string; name: string; coachName: string }) {
  const [copied, setCopied] = useState(false);
  const origin = useSyncExternalStore(noop, () => window.location.origin, () => "");
  const url = `${origin}/go/${code}`;
  const message = `Hey ${name.split(" ")[0]}, here's your workout with Brodie from Coach ${coachName}: ${url}`;
  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked: the link is still selectable */
    }
  }
  async function share() {
    if (navigator.share) await navigator.share({ title: "Your workout with Brodie", text: message }).catch(() => {});
    else window.location.href = `sms:?&body=${encodeURIComponent(message)}`;
  }
  return (
    <div className="rounded-xl bg-zinc-950/40 px-4 py-3">
      <p className="text-xs text-zinc-500">Workout link · {name.split(" ")[0]} opens this to train with Brodie</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded-md bg-zinc-900 px-2 py-1.5 text-xs text-zinc-300" title={url}>
          {url}
        </code>
        <button type="button" onClick={copy} className="rounded-full bg-zinc-50 px-3 py-1.5 text-xs font-medium text-zinc-950">
          {copied ? "Copied" : "Copy"}
        </button>
        <button type="button" onClick={share} className="rounded-full border border-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-100">
          Text it
        </button>
      </div>
    </div>
  );
}
