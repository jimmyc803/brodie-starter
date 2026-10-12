// Patterns that must never appear in public HTML/JSON.
/** @type {[string, RegExp][]} */
const PATTERNS = [
  ["phone", /(?<![\w.])(?:\+?1[\s.-]?)?\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b/],
  ["phone-e164", /\+\d{10,15}\b/],
  ["email", /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/],
];

export function findPii(text) {
  const hits = [];
  for (const [kind, re] of PATTERNS) {
    const m = text.match(re);
    if (m) hits.push({ kind, sample: m[0] });
  }
  return hits;
}
