import "server-only";

import { timingSafeEqual } from "node:crypto";

// The team's review page is /admin/<ADMIN_KEY>. No key configured = no admin page.
export function isAdminKey(key: string): boolean {
  const want = process.env.ADMIN_KEY ?? "";
  if (want.length < 24) return false;
  const a = Buffer.from(key), b = Buffer.from(want);
  return a.length === b.length && timingSafeEqual(a, b);
}
