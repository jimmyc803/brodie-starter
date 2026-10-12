#!/usr/bin/env node
// Usage: node scripts/pii-check.mjs <url> [<url>...]
// Fetches each URL and exits 1 if phone numbers or emails appear.
import { pathToFileURL } from "node:url";
import { findPii } from "./pii-lib.mjs";

export async function checkUrls(urls, fetchFn = fetch) {
  const failures = [];
  for (const url of urls) {
    const res = await fetchFn(url);
    const text = await res.text();
    for (const hit of findPii(text)) failures.push({ url, ...hit });
  }
  return failures;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const urls = process.argv.slice(2);
  if (urls.length === 0) {
    console.error("usage: pii-check.mjs <url>...");
    process.exit(2);
  }
  const failures = await checkUrls(urls);
  for (const f of failures) console.error(`PII (${f.kind}) at ${f.url}: ${f.sample}`);
  if (failures.length > 0) process.exit(1);
  console.log(`pii-check ok: ${urls.length} url(s)`);
}
