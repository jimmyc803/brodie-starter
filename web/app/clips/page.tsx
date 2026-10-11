import type { Metadata } from "next";

import { ClipsDev } from "@/app/clips/clips-dev";

export const metadata: Metadata = { title: "Rep review clips · Brodie for Coaches", robots: { index: false } };

// Dev route: every rep review clip in clips.config.ts, with upload (+ landmark caching) and a player preview.
export default function ClipsPage() {
  return <ClipsDev />;
}
