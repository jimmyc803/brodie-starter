"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { createMaxWaitDebounce } from "@/lib/throttle";
import type { RealtimeChannel, SupabaseClient } from "@supabase/supabase-js";

const RECONCILE_MS = 30_000;

/**
 * Subscribes to site_pulse changes and refreshes server data (debounced 500ms, never delayed >1s).
 * Also refreshes on every (re)subscribe and every 30s to reconcile missed events.
 */
export function LiveRefresh() {
  const router = useRouter();

  useEffect(() => {
    const refresher = createMaxWaitDebounce(() => router.refresh(), 500, 1000);
    const interval = setInterval(() => router.refresh(), RECONCILE_MS);
    let disposed = false;
    let sb: SupabaseClient | null = null;
    let channel: RealtimeChannel | undefined;
    // Load the realtime client after first paint so it stays out of the critical bundle.
    void import("@/lib/supabase-browser")
      .then(({ getBrowserClient }) => {
        if (disposed) return;
        sb = getBrowserClient();
        channel = sb
          ?.channel("site_pulse")
          .on("postgres_changes", { event: "*", schema: "public", table: "site_pulse" }, refresher.trigger)
          .subscribe((status) => {
            if (status === "SUBSCRIBED") refresher.trigger();
          });
      })
      .catch((err: unknown) => console.error("live refresh unavailable", err));
    return () => {
      disposed = true;
      refresher.cancel();
      clearInterval(interval);
      if (sb && channel) void sb.removeChannel(channel);
    };
  }, [router]);

  return null;
}
