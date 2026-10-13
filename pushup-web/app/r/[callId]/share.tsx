"use client";

import { useState } from "react";

export function ShareResult({ title }: { title: string }) {
  const [status, setStatus] = useState("");
  async function share() {
    try {
      if (navigator.share) {
        await navigator.share({ title, url: window.location.href });
        setStatus("Shared.");
      } else {
        await navigator.clipboard.writeText(window.location.href);
        setStatus("Result link copied.");
      }
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") return;
      setStatus("Could not share. Copy the link from your address bar.");
    }
  }
  return (
    <div>
      <button type="button" onClick={share} className="press inline-flex min-h-12 items-center border-2 border-ink bg-pink px-6 font-display text-xl text-ink uppercase">Share result</button>
      <p role="status" className="mt-2 text-sm text-ink-2">{status}</p>
    </div>
  );
}
