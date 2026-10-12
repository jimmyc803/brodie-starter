import assert from 'node:assert/strict';
import { test, afterEach } from 'node:test';
// @ts-expect-error Node's native TypeScript runner requires the .ts extension.
import { parseProgram, normalizeProgram, MAX_PDF_BYTES, ProgramParseError } from '../lib/parseProgram.ts';

const originalFetch = globalThis.fetch;
const originalKey = process.env.GEMINI_PARSER_API_KEY;
afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalKey === undefined) delete process.env.GEMINI_PARSER_API_KEY;
  else process.env.GEMINI_PARSER_API_KEY = originalKey;
});
const exercise = (name: string) => ({name, sets: 3, reps: 10, notes: '', exercise_key: 'squat', supported: true});
const program = () => ({title: 'Tristan — Strength', days: [{day_number: 1, title: 'Day 1', exercises: ['Squats', 'Push-ups', 'Lunges', 'Jumping jacks', 'Dumbbell bicep curls', 'Pull-ups', 'Bench press', 'Bulgarian split squats'].map(exercise)}]});
const pdf = Buffer.from('%PDF-1.7\n test document\n%%EOF');

test('derives supported keys from exercise names, never trusting model claims', () => {
  const parsed = normalizeProgram(program());
  assert.deepEqual(parsed.days[0].exercises.map((e: {exercise_key: string|null}) => e.exercise_key), ['squat', 'pushup', 'lunge', 'jumping_jack', 'bicep_curl', 'pullup', null, null]);
  assert.equal(parsed.days[0].exercises[5].supported, true);
  assert.equal(parsed.days[0].exercises[6].supported, false);
});
test('rejects malformed programs and duplicate days', () => {
  for (const value of [null, {}, {title: 'Empty', days: []}, {...program(), title: ''}]) assert.throws(() => normalizeProgram(value));
  const bad = program(); bad.days[0].exercises[0].reps = 1.5;
  assert.throws(() => normalizeProgram(bad), /reps/);
  const duplicate = program(); duplicate.days.push(duplicate.days[0]);
  assert.throws(() => normalizeProgram(duplicate), /day_number/);
});
test('rejects bad PDFs before network access', async () => {
  globalThis.fetch = async () => {throw new Error('network must not be called');};
  await assert.rejects(parseProgram(Buffer.from('not a pdf')), /PDF/);
  await assert.rejects(parseProgram(Buffer.alloc(MAX_PDF_BYTES + 1)), /10 MB/);
});
test('requires the dedicated parser key', async () => {
  delete process.env.GEMINI_PARSER_API_KEY;
  await assert.rejects(parseProgram(pdf), /GEMINI_PARSER_API_KEY/);
});
test('sends PDF and structured schema through Gemini REST and normalizes output', async () => {
  process.env.GEMINI_PARSER_API_KEY = 'offline-test-key';
  globalThis.fetch = async (url, options) => {
    assert.match(String(url), /^https:\/\/generativelanguage.googleapis.com\/v1beta\/models\//);
    assert.equal((options?.headers as Record<string,string>)['x-goog-api-key'], 'offline-test-key');
    const body = JSON.parse(String(options?.body));
    assert.equal(body.contents[0].parts[1].inline_data.data, pdf.toString('base64'));
    assert.equal(body.generationConfig.responseMimeType, 'application/json');
    return Response.json({candidates:[{finishReason:'STOP',content:{parts:[{text: JSON.stringify(program())}]}}]});
  };
  const result = await parseProgram(pdf);
  assert.equal(result.days[0].exercises[6].exercise_key, null);
});
test('does not leak provider error bodies and rejects blocked, truncated or malformed output', async () => {
  process.env.GEMINI_PARSER_API_KEY = 'offline-test-key';
  globalThis.fetch = async () => new Response('secret-value', {status: 403});
  await assert.rejects(parseProgram(pdf), (e: Error) => /403/.test(e.message) && !/secret-value/.test(e.message));
  for (const response of [
    {promptFeedback:{blockReason:'SAFETY'}},
    {candidates:[{finishReason:'MAX_TOKENS', content:{parts:[{text:JSON.stringify(program())}]}}]},
    {candidates:[{finishReason:'STOP', content:{parts:[{text:'not json'}]}}]},
  ]) {
    globalThis.fetch = async () => Response.json(response);
    await assert.rejects(parseProgram(pdf));
  }
});

test('classifies provider HTTP failures without reading or exposing provider bodies', async () => {
  process.env.GEMINI_PARSER_API_KEY = 'offline-test-key';
  for (const [status, code] of [[401, 'PROVIDER_AUTH'], [403, 'PROVIDER_AUTH'], [429, 'PROVIDER_QUOTA'], [404, 'PROVIDER_MODEL'], [400, 'PROVIDER_REQUEST'], [503, 'PROVIDER_ERROR']] as const) {
    globalThis.fetch = async () => {
      const response = new Response('private-document-and-key', { status });
      response.text = async () => { throw Error('must not read provider body'); };
      response.json = async () => { throw Error('must not read provider body'); };
      return response;
    };
    await assert.rejects(parseProgram(pdf), (error: unknown) => error instanceof ProgramParseError && error.code === code && !error.message.includes('private-document-and-key'));
  }
});

test('distinguishes connection failures from timeouts without exposing thrown messages', async () => {
  process.env.GEMINI_PARSER_API_KEY = 'offline-test-key';
  for (const [name, code] of [['TimeoutError', 'PROVIDER_TIMEOUT'], ['AbortError', 'PROVIDER_TIMEOUT'], ['TypeError', 'PROVIDER_NETWORK']] as const) {
    globalThis.fetch = async () => { const error = new Error('private-network-detail'); error.name = name; throw error; };
    await assert.rejects(parseProgram(pdf), (error: unknown) => error instanceof ProgramParseError && error.code === code && !error.message.includes('private-network-detail'));
  }
});
