"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { getBrowserClient } from "@/lib/supabase-browser";

/** Subscribes to site_pulse changes and refreshes server data (debounced 500ms). */
export function LiveRefresh() {
  const router = useRouter();

  useEffect(() => {
    const sb = getBrowserClient();
    if (!sb) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const channel = sb
      .channel("site_pulse")
      .on("postgres_changes", { event: "*", schema: "public", table: "site_pulse" }, () => {
        clearTimeout(timer);
        timer = setTimeout(() => router.refresh(), 500);
      })
      .subscribe();
    return () => {
      clearTimeout(timer);
      void sb.removeChannel(channel);
    };
  }, [router]);

  return null;
}
