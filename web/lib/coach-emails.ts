// The emails a coach gets: their private link at sign-up, a note when they're approved, and the link again on request.
// Plain text plus simple HTML; every link is the coach's private dashboard link, which is their only key.

type Msg = { subject: string; text: string; html: string };
type Account = { name: string; link: string };

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
const KEEP = "This link is your login: anyone with it can see your clients, so keep it private and bookmark it.";

function html(paragraphs: string[], button?: Account & { label: string }): string {
  const p = paragraphs.map((t) => `<p style="margin:0 0 14px">${t}</p>`).join("");
  const b = button
    ? `<p style="margin:20px 0"><a href="${esc(button.link)}" style="background:#141414;color:#f3f1ec;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:600">${esc(button.label)}</a></p><p style="margin:0 0 14px;font-size:13px;color:#55524c">Or paste this link: <a href="${esc(button.link)}" style="color:#141414">${esc(button.link)}</a></p>`
    : "";
  return `<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:15px;line-height:1.5;color:#141414;max-width:520px">${p}${b}<p style="margin:24px 0 0;font-size:13px;color:#8a867f">${esc(KEEP)}</p><p style="margin:8px 0 0;font-size:13px;color:#8a867f">Brodie for Coaches</p></div>`;
}

export function welcomeEmail({ name, link }: Account): Msg {
  return {
    subject: "Your Brodie coach link",
    text: [
      `Hi ${name},`,
      "Thanks for applying to coach with Brodie. Here's your private coach dashboard:",
      link,
      "You can explore with a demo client and upload your program PDF right away. We review every coach personally (usually within 24 hours); once you're approved you can add real clients.",
      KEEP,
      "Brodie for Coaches",
    ].join("\n\n"),
    html: html(
      [`Hi ${esc(name)},`, "Thanks for applying to coach with Brodie. You can explore with a demo client and upload your program PDF right away.", "We review every coach personally (usually within 24 hours). Once you're approved you can add real clients."],
      { name, link, label: "Open your dashboard" },
    ),
  };
}

export function approvedEmail({ name, link }: Account): Msg {
  return {
    subject: "You're approved to coach with Brodie",
    text: [
      `Hi ${name},`,
      "You're approved. You can now add your real clients, assign them a training day and text them their workout link.",
      link,
      KEEP,
      "Brodie for Coaches",
    ].join("\n\n"),
    html: html(
      [`Hi ${esc(name)},`, "You're approved. You can now add your real clients, assign them a training day and text them their workout link."],
      { name, link, label: "Add your first client" },
    ),
  };
}

export function linkEmail(accounts: Account[]): Msg {
  const many = accounts.length > 1;
  return {
    subject: "Your Brodie coach link",
    text: [
      "Here's the coach link you asked for:",
      ...accounts.map((a) => (many ? `${a.name}: ${a.link}` : a.link)),
      "If you didn't ask for this, you can ignore it.",
      KEEP,
      "Brodie for Coaches",
    ].join("\n\n"),
    html: many
      ? html(["Here are the coach links you asked for:", ...accounts.map((a) => `${esc(a.name)}: <a href="${esc(a.link)}" style="color:#141414">${esc(a.link)}</a>`), "If you didn't ask for this, you can ignore it."])
      : html(["Here's the coach link you asked for. If you didn't ask for this, you can ignore it."], { ...accounts[0], label: "Open your dashboard" }),
  };
}

const RESEND_AFTER_MS = 10 * 60 * 1000;
export const LINK_EMAILS_PER_HOUR = 50;
// "Email me my link": at most one email per account every 10 minutes, and a site-wide hourly cap against floods.
export function mayEmailLink(lastSentAt: string | null, sentThisHour: number, now = new Date()): boolean {
  if (sentThisHour >= LINK_EMAILS_PER_HOUR) return false;
  return !lastSentAt || now.getTime() - new Date(lastSentAt).getTime() >= RESEND_AFTER_MS;
}
