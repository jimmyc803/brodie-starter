import { afterEach, describe, expect, it, vi } from "vitest";
import { approvedEmail, linkEmail, mayEmailLink, welcomeEmail } from "@/lib/coach-emails";
import { sendEmail } from "@/lib/email";

const link = "https://brodie.example/c/tok_123";

describe("welcomeEmail", () => {
  it("greets the coach and carries their private link", () => {
    const m = welcomeEmail({ name: "Tristan", link });
    expect(m.subject).toMatch(/Brodie/);
    expect(m.text).toContain("Hi Tristan");
    expect(m.text).toContain(link);
    expect(m.html).toContain(`href="${link}"`);
    expect(m.text).toMatch(/keep it private|don't share/i);
  });
  it("escapes the name in HTML", () => {
    expect(welcomeEmail({ name: "<b>x</b>", link }).html).not.toContain("<b>x</b>");
  });
});

describe("approvedEmail", () => {
  it("says they're approved and links the dashboard", () => {
    const m = approvedEmail({ name: "Tristan", link });
    expect(m.subject).toMatch(/approved/i);
    expect(m.text).toContain(link);
    expect(m.text).toMatch(/add (your )?(real )?clients/i);
  });
});

describe("linkEmail", () => {
  it("lists every coach account on that email", () => {
    const m = linkEmail([{ name: "Tristan", link }, { name: "Tristan (gym)", link: link + "2" }]);
    expect(m.text).toContain(link);
    expect(m.text).toContain(link + "2");
    expect(m.html).toContain(`href="${link}2"`);
  });
});

describe("mayEmailLink", () => {
  const now = new Date("2026-10-12T12:00:00Z");
  it("allows a first request", () => expect(mayEmailLink(null, 0, now)).toBe(true));
  it("blocks a repeat within 10 minutes", () => expect(mayEmailLink("2026-10-12T11:55:00Z", 0, now)).toBe(false));
  it("allows a repeat after 10 minutes", () => expect(mayEmailLink("2026-10-12T11:49:00Z", 0, now)).toBe(true));
  it("blocks when the site has sent 50 link emails this hour", () => expect(mayEmailLink(null, 50, now)).toBe(false));
});

describe("sendEmail", () => {
  afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });
  const msg = { to: "c@x.com", subject: "s", text: "t", html: "<p>t</p>" };
  it("does nothing without RESEND_API_KEY", async () => {
    vi.stubEnv("RESEND_API_KEY", "");
    const f = vi.fn(); vi.stubGlobal("fetch", f);
    expect(await sendEmail(msg)).toBe(false);
    expect(f).not.toHaveBeenCalled();
  });
  it("posts to Resend with the configured sender", async () => {
    vi.stubEnv("RESEND_API_KEY", "re_test"); vi.stubEnv("EMAIL_FROM", "Brodie <hi@brodie.example>");
    const f = vi.fn().mockResolvedValue(new Response("{}", { status: 200 })); vi.stubGlobal("fetch", f);
    expect(await sendEmail(msg)).toBe(true);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("https://api.resend.com/emails");
    expect(init.headers.Authorization).toBe("Bearer re_test");
    expect(JSON.parse(init.body)).toMatchObject({ from: "Brodie <hi@brodie.example>", to: ["c@x.com"], subject: "s" });
  });
  it("never throws when Resend fails", async () => {
    vi.stubEnv("RESEND_API_KEY", "re_test");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    expect(await sendEmail(msg)).toBe(false);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("bad", { status: 422 })));
    expect(await sendEmail(msg)).toBe(false);
  });
});
