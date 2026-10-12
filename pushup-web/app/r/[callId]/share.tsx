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
      <button type="button" onClick={share} className="rounded-lg bg-accent px-5 py-3 font-bold text-on-accent">Share result</button>
      <p role="status" className="mt-2 text-sm text-ink-2">{status}</p>
    </div>
  );
}
