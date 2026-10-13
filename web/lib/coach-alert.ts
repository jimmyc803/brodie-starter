import "server-only";

// Tell the team about a new coach application. COACH_ALERT_WEBHOOK is a Slack or Discord incoming-webhook URL (server-only);
// without it this does nothing. Never throws: a failed alert must not fail the sign-up.
export async function alertNewCoach(lines: string[]): Promise<void> {
  const url = process.env.COACH_ALERT_WEBHOOK;
  if (!url) return;
  const text = lines.join("\n");
  const body = /discord(app)?\.com\//.test(url) ? { content: text.slice(0, 1900) } : { text };
  try {
    await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(4000) });
  } catch {
    /* best effort */
  }
}
