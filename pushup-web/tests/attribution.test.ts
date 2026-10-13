import { describe, expect, it } from "vitest";
import {
  cleanRef,
  cleanSrc,
  isSameOriginRequest,
  joinBody,
  joinSmsHref,
  parseVisit,
  referrerHost,
  retagSmsHref,
  tagsFromParams,
} from "../lib/attribution";
import { smsLink } from "../lib/format";

describe("tags", () => {
  it("cleans invite codes and sources", () => {
    expect(cleanRef(" k7x2qb ")).toBe("K7X2QB");
    expect(cleanRef(["AB12", "ZZ"])).toBe("AB12");
    expect(cleanRef("no!")).toBeNull();
    expect(cleanRef(undefined)).toBeNull();
    expect(cleanSrc("TikTok")).toBe("tiktok");
    expect(cleanSrc("ig_story")).toBe("ig_story");
    expect(cleanSrc("bad source")).toBeNull();
    expect(cleanSrc("stop")).toBeNull(); // would read as STOP to the SMS parser
  });

  it("reads ref and src (or utm_source) from either param shape", () => {
    expect(tagsFromParams(new URLSearchParams("ref=k7x2qb&utm_source=TikTok"))).toEqual({ ref: "K7X2QB", src: "tiktok" });
    expect(tagsFromParams({ src: "ig", utm_source: "x" })).toEqual({ ref: null, src: "ig" });
    expect(tagsFromParams({})).toEqual({ ref: null, src: null });
  });

  it("builds the pre-filled body with the name going last", () => {
    expect(joinBody()).toBe("JOIN ");
    expect(joinBody({ ref: "K7X2QB", src: null })).toBe("JOIN ref-K7X2QB ");
    expect(joinBody({ ref: "K7X2QB", src: "tiktok" })).toBe("JOIN ref-K7X2QB src-tiktok ");
    expect(joinSmsHref(null, { ref: "AB12", src: null })).toBeNull();
  });

  it("keeps smsLink backward compatible", () => {
    expect(smsLink("+15551234567")).toBe("sms:+15551234567&body=JOIN%20");
    expect(smsLink("+15551234567", { ref: "AB12", src: null })).toBe("sms:+15551234567&body=JOIN%20ref-AB12%20");
  });

  it("retags only untagged JOIN sms links", () => {
    const tags = { ref: "AB12", src: "ig" };
    expect(retagSmsHref("sms:+15551234567&body=JOIN%20", tags)).toBe("sms:+15551234567&body=JOIN%20ref-AB12%20src-ig%20");
    expect(retagSmsHref("sms:+1555?body=JOIN%20&x=1", tags)).toBe("sms:+1555?body=JOIN%20ref-AB12%20src-ig%20&x=1");
    const already = "sms:+1555&body=JOIN%20ref-ZZ99%20";
    expect(retagSmsHref(already, tags)).toBe(already);
    expect(retagSmsHref("sms:+1555&body=LINK%20123456", tags)).toBe("sms:+1555&body=LINK%20123456");
    expect(retagSmsHref("sms:+1555&body=%E0%A4%A", tags)).toBe("sms:+1555&body=%E0%A4%A");
    expect(retagSmsHref("sms:+1555&body=JOIN%20", { ref: null, src: null })).toBe("sms:+1555&body=JOIN%20");
    expect(retagSmsHref("https://x.test", tags)).toBe("https://x.test");
  });
});

describe("visits", () => {
  it("keeps only the referrer domain, and nothing for same-site or junk", () => {
    expect(referrerHost("https://www.tiktok.com/@brodie/video/1?x=y", "brodie.test")).toBe("tiktok.com");
    expect(referrerHost("https://brodie.test/rules", "www.brodie.test")).toBeNull();
    expect(referrerHost("", "brodie.test")).toBeNull();
    expect(referrerHost("not a url", "brodie.test")).toBeNull();
  });

  it("validates beacon bodies and strips query strings", () => {
    expect(parseVisit({ kind: "landing", path: "/join?ref=AB12#top", src: "TikTok", ref: "ab12", referrer_host: "T.co" })).toEqual({
      kind: "landing",
      path: "/join",
      src: "tiktok",
      ref: "AB12",
      referrer_host: "t.co",
    });
    expect(parseVisit({ kind: "join_tap", path: "/", referrer_host: "bad host/" })?.referrer_host).toBeNull();
    for (const bad of [null, [], "x", { kind: "pageview", path: "/" }, { kind: "landing", path: "//evil.test" }, { kind: "landing" }]) {
      expect(parseVisit(bad)).toBeNull();
    }
  });

  it("accepts only same-origin beacons", () => {
    const h = (o: Record<string, string>) => new Headers(o);
    expect(isSameOriginRequest(h({ "sec-fetch-site": "same-origin", origin: "https://b.test", host: "b.test" }))).toBe(true);
    expect(isSameOriginRequest(h({ "sec-fetch-site": "same-origin", host: "b.test" }))).toBe(true);
    expect(isSameOriginRequest(h({ "sec-fetch-site": "cross-site", origin: "https://b.test", host: "b.test" }))).toBe(false);
    expect(isSameOriginRequest(h({ origin: "https://evil.test", host: "b.test" }))).toBe(false);
    expect(isSameOriginRequest(h({ origin: "https://b.test", host: "b.test" }))).toBe(true);
    expect(isSameOriginRequest(h({ host: "b.test" }))).toBe(false);
  });
});
