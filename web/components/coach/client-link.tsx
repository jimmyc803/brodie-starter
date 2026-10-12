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
    <div className="rounded-[10px] bg-canvas px-4 py-3">
      <p className="text-xs text-ink-3">Workout link · {name.split(" ")[0]} opens this to train with Brodie</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded-md bg-surface px-2 py-1.5 text-xs text-ink-2" title={url}>
          {url}
        </code>
        <button type="button" onClick={copy} className="rounded-full bg-ink px-3 py-1.5 text-xs font-medium text-canvas">
          {copied ? "Copied" : "Copy"}
        </button>
        <button type="button" onClick={share} className="rounded-full border border-line-strong px-3 py-1.5 text-xs font-medium text-ink">
          Text it
        </button>
      </div>
    </div>
  );
}
