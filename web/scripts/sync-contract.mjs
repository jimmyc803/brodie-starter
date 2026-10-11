// Copies the team contract from the repo root into web/lib/generated/ so the app never imports files outside web/
// (Turbopack would otherwise have to watch the whole repo, including the Python venv and model files).
// Sources: shared/muscles.json, db/fixtures/sample_session.json, src/rtcoach/cues.json (fault label -> spoken cue).
// Runs before dev and build; Vercel clones the whole repo, so the sources exist there too.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const root = path.resolve(web, "..");
const out = path.join(web, "lib", "generated");
fs.mkdirSync(out, { recursive: true });

const read = (rel) => JSON.parse(fs.readFileSync(path.join(root, rel), "utf8"));
const write = (name, data) => fs.writeFileSync(path.join(out, name), JSON.stringify(data, null, 2) + "\n");

write("muscles.json", read("shared/muscles.json"));
write("sample_session.json", read("db/fixtures/sample_session.json"));

const cues = read("src/rtcoach/cues.json");
const faultCues = {};
for (const [label, v] of Object.entries(cues)) if (v && v.kind === "fault" && v.cue) faultCues[label] = v.cue;
write("fault_cues.json", faultCues);

console.log(`sync-contract: wrote muscles.json, sample_session.json, fault_cues.json (${Object.keys(faultCues).length} cues)`);
