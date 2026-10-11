// Test-process external-service boundary only. Production imports are untouched.
const fs = require('node:fs');
const originalFetch = globalThis.fetch;
globalThis.fetch = async function(input, init) {
  const url = typeof input === 'string' ? input : input.url || String(input);
  if (new URL(url, 'http://localhost').hostname === 'generativelanguage.googleapis.com') {
    if (init?.headers?.['x-goog-api-key'] !== 'local-harness-parser-key') throw Error('Harness parser key missing');
    const request = JSON.parse(init.body);
    const pdf = Buffer.from(request.contents[0].parts[1].inline_data.data, 'base64');
    const expectedPdf = fs.readFileSync(process.env.HARNESS_PDF);
    if (!pdf.equals(expectedPdf)) throw Error('Parser did not send the uploaded PDF');
    const mode = fs.readFileSync(process.env.HARNESS_GEMINI_MODE, 'utf8').trim();
    fs.appendFileSync(process.env.HARNESS_GEMINI_CALLS, JSON.stringify({bytes: pdf.length, mode}) + '\n');
    if (mode === 'failure') return Response.json({error: {message: 'Deterministic provider outage'}}, {status: 503});
    const program = JSON.parse(fs.readFileSync(process.env.HARNESS_PROGRAM, 'utf8'));
    // Provider does not supply trusted exercise keys or flags; real parser derives them.
    for (const day of program.days) for (const e of day.exercises) { delete e.exercise_key; delete e.supported; }
    if (mode === 'invalid-schema') program.days[0].exercises[0].sets = -1;
    if (mode === 'forged-support') {
      program.title = 'Manual-only adversarial program';
      program.days = [{day_number: 1, title: 'Bench-only day', exercises: [{name: 'Bench press', sets: 3, reps: 10, notes: 'Manual exercise', exercise_key: 'squat', supported: true}]}];
    }
    if (!['success', 'invalid-schema', 'malformed-json', 'forged-support'].includes(mode)) throw Error('Unknown Gemini fixture mode');
    const text = mode === 'malformed-json' ? '{not valid JSON' : JSON.stringify(program);
    return Response.json({candidates: [{finishReason: 'STOP', content: {parts: [{text}]}}]});
  }
  if (!['localhost', '127.0.0.1', '[::1]'].includes(new URL(url, 'http://localhost').hostname)) throw Error('Harness blocked unexpected external fetch');
  return originalFetch(input, init);
};
