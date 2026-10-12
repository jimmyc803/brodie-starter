import "server-only";

export type Email = { to: string; subject: string; text: string; html: string };

// Send one email through Resend. RESEND_API_KEY and EMAIL_FROM ("Brodie <hello@yourdomain>", a verified Resend domain) are
// server-only; without the key this does nothing. Never throws: a failed email must not fail the sign-up or approval.
export async function sendEmail(m: Email): Promise<boolean> {
  const key = process.env.RESEND_API_KEY;
  if (!key) return false;
  const body = {
    from: process.env.EMAIL_FROM || "Brodie <onboarding@resend.dev>",
    to: [m.to],
    subject: m.subject,
    text: m.text,
    html: m.html,
    ...(process.env.EMAIL_REPLY_TO ? { reply_to: process.env.EMAIL_REPLY_TO } : {}),
  };
  try {
    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(5000),
    });
    return res.ok;
  } catch {
    return false;
  }
}
