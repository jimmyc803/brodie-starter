"use client";

import { useEffect } from "react";
import {
  NO_TAGS,
  cleanRef,
  cleanSrc,
  hasTags,
  referrerHost,
  retagSmsHref,
  tagsFromParams,
  type JoinTags,
  type VisitKind,
} from "@/lib/attribution";

const TAGS_KEY = "brodie_join_tags";
const LANDED_KEY = "brodie_landed";

/** sessionStorage can throw (storage disabled, some private modes); attribution is best effort there. */
function storageGet(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string): void {
  try {
    window.sessionStorage.setItem(key, value);
  } catch {
    // Storage unavailable: the visit is still counted, the tags just won't follow the visitor to another page.
  }
}

function storedTags(): JoinTags {
  const raw = storageGet(TAGS_KEY);
  if (!raw) return NO_TAGS;
  try {
    const v = JSON.parse(raw) as { ref?: unknown; src?: unknown };
    return { ref: cleanRef(v.ref), src: cleanSrc(v.src) };
  } catch {
    return NO_TAGS;
  }
}

function report(kind: VisitKind, tags: JoinTags, refHost: string | null): void {
  const body = JSON.stringify({ kind, path: window.location.pathname, src: tags.src, ref: tags.ref, referrer_host: refHost });
  // Fire-and-forget: counting must never slow down or break the page, so a failed beacon is dropped on purpose.
  void fetch("/api/visit", { method: "POST", headers: { "content-type": "application/json" }, body, keepalive: true }).catch(
    () => undefined,
  );
}

/**
 * First-party, cookie-free visit counting for the growth funnel: one "landing" per browser tab session and one
 * "join_tap" per tap on a pre-filled JOIN text link. Sends only the page path, the link's ?ref=/?src= tags and the
 * referring site's domain; no cookies, no identifiers. Also carries ?ref=/?src= from the landing page into every
 * "Text JOIN" link the visitor taps later in the session.
 */
export function VisitBeacon() {
  useEffect(() => {
    const admin = window.location.pathname.startsWith("/admin");
    const bot = typeof navigator !== "undefined" && navigator.webdriver === true;
    const fromUrl = tagsFromParams(new URLSearchParams(window.location.search));
    if (hasTags(fromUrl)) storageSet(TAGS_KEY, JSON.stringify(fromUrl));

    if (!admin && !bot && storageGet(LANDED_KEY) !== "1") {
      storageSet(LANDED_KEY, "1");
      report("landing", storedTags(), referrerHost(document.referrer, window.location.host));
    }

    const onClick = (e: MouseEvent) => {
      const el = e.target instanceof Element ? e.target.closest("a[href^='sms:']") : null;
      if (!(el instanceof HTMLAnchorElement)) return;
      const tags = storedTags();
      const href = el.getAttribute("href") ?? "";
      const tagged = retagSmsHref(href, tags);
      if (tagged !== href) el.setAttribute("href", tagged);
      if (!window.location.pathname.startsWith("/admin") && !bot) report("join_tap", tags, null);
    };
    // Capture phase: the href is rewritten before the browser follows the link.
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, []);
  return null;
}
