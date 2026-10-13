/**
 * Join attribution (client-safe, pure). A site link like /join?ref=K7X2QB or /join?src=tiktok pre-fills the SMS body
 * as "JOIN ref-K7X2QB " / "JOIN src-tiktok "; the texter types their name after it. The messaging handler
 * (challenge/messaging/commands.py split_join_arg) pulls the tags out wherever they appear, so plain "JOIN name" still
 * works. Tags carry no personal data: an invite code and a link label.
 */

export type JoinTags = { ref: string | null; src: string | null };

export const NO_TAGS: JoinTags = { ref: null, src: null };

const REF_RE = /^[A-Za-z0-9]{4,12}$/;
const SRC_RE = /^[a-z0-9_]{1,24}$/;
// The SMS parser treats a standalone "stop" anywhere in a text as STOP; never put it in a pre-filled body.
const RESERVED_SRC = new Set(["stop"]);

function first(v: unknown): string | null {
  if (Array.isArray(v)) return first(v[0]);
  return typeof v === "string" ? v : null;
}

/** A participant's invite code, upper-cased, or null when malformed. */
export function cleanRef(v: unknown): string | null {
  const s = first(v)?.trim() ?? "";
  return REF_RE.test(s) ? s.toUpperCase() : null;
}

/** A link source label (e.g. "tiktok"), lower-cased, or null when malformed or reserved. */
export function cleanSrc(v: unknown): string | null {
  const s = first(v)?.trim().toLowerCase() ?? "";
  return SRC_RE.test(s) && !RESERVED_SRC.has(s) ? s : null;
}

type ParamSource = URLSearchParams | Record<string, string | string[] | undefined>;

/** ref from ?ref=, source from ?src= (or ?utm_source=). */
export function tagsFromParams(params: ParamSource): JoinTags {
  const get = (k: string) => (params instanceof URLSearchParams ? params.get(k) : params[k]);
  return { ref: cleanRef(get("ref")), src: cleanSrc(get("src")) ?? cleanSrc(get("utm_source")) };
}

export function hasTags(tags: JoinTags): boolean {
  return Boolean(tags.ref || tags.src);
}

/** The pre-filled SMS body: "JOIN " plus any tags, ending in a space so the name goes last. */
export function joinBody(tags: JoinTags = NO_TAGS): string {
  const parts = ["JOIN"];
  if (tags.ref) parts.push(`ref-${tags.ref}`);
  if (tags.src) parts.push(`src-${tags.src}`);
  return `${parts.join(" ")} `;
}

export function joinSmsHref(brodieNumber: string | null, tags: JoinTags = NO_TAGS): string | null {
  if (!brodieNumber) return null;
  return `sms:${brodieNumber}&body=${encodeURIComponent(joinBody(tags))}`;
}

/**
 * Add tags to an existing pre-filled JOIN link (the site-wide buttons are rendered without them). Leaves anything that
 * is not an untagged "sms:...&body=JOIN " link untouched.
 */
export function retagSmsHref(href: string, tags: JoinTags): string {
  if (!href.startsWith("sms:") || !hasTags(tags)) return href;
  const at = href.search(/[?&]body=/);
  if (at < 0) return href;
  const start = href.indexOf("=", at) + 1;
  const endRel = href.slice(start).indexOf("&");
  const end = endRel < 0 ? href.length : start + endRel;
  let body: string;
  try {
    body = decodeURIComponent(href.slice(start, end));
  } catch {
    return href;
  }
  if (body.trim().toUpperCase() !== "JOIN") return href;
  return href.slice(0, start) + encodeURIComponent(joinBody(tags)) + href.slice(end);
}

/** The referring site's host (no path, no query), or null for same-site, empty or unparsable referrers. */
export function referrerHost(referrer: string, ownHost: string): string | null {
  if (!referrer) return null;
  let host: string;
  try {
    host = new URL(referrer).hostname.toLowerCase();
  } catch {
    return null;
  }
  host = host.replace(/^www\./, "");
  const own = ownHost.toLowerCase().replace(/^www\./, "").replace(/:\d+$/, "");
  if (!host || host === own || !/^[a-z0-9.-]{1,100}$/.test(host)) return null;
  return host;
}

export type VisitKind = "landing" | "join_tap";

export type VisitPayload = {
  kind: VisitKind;
  path: string;
  src: string | null;
  ref: string | null;
  referrer_host: string | null;
};

/**
 * Browser same-origin check for the visit beacon: Sec-Fetch-Site (all current browsers) must be same-origin, and an
 * Origin header, when present, must match Host. Not authentication: it only keeps other sites from posting counts.
 */
export function isSameOriginRequest(h: Headers): boolean {
  const site = h.get("sec-fetch-site");
  if (site !== null && site !== "same-origin") return false;
  const origin = h.get("origin");
  const host = h.get("host");
  if (origin === null) return site === "same-origin";
  try {
    return host !== null && new URL(origin).host === host;
  } catch {
    return false;
  }
}

/** Validate an untrusted /api/visit body. Returns null when it is not a well-formed visit. */
export function parseVisit(body: unknown): VisitPayload | null {
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  const b = body as Record<string, unknown>;
  if (b.kind !== "landing" && b.kind !== "join_tap") return null;
  if (typeof b.path !== "string" || !b.path.startsWith("/") || b.path.startsWith("//")) return null;
  const path = b.path.split(/[?#]/)[0].slice(0, 120);
  const host = typeof b.referrer_host === "string" ? b.referrer_host.toLowerCase().trim() : "";
  return {
    kind: b.kind,
    path,
    src: cleanSrc(b.src),
    ref: cleanRef(b.ref),
    referrer_host: /^[a-z0-9.-]{1,100}$/.test(host) ? host : null,
  };
}
