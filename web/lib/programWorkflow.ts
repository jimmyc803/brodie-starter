/** Framework-independent orchestration; adapters keep credentials on the server. */
export const MAX_UPLOAD_BYTES = 3 * 1024 * 1024;
export type ActionState = { ok: boolean; message: string };
export type Coach = { id: string; name: string };
export interface ProgramStore<T> {
  coach(token: string): Promise<Coach | null>;
  upload(path: string, bytes: Uint8Array): Promise<void>;
  remove(path: string): Promise<void>;
  save(token: string, path: string, program: T): Promise<void>;
  assign(token: string, clientId: string, dayId: string): Promise<void>;
}
export class WorkflowError extends Error {}
export function validToken(token: string): boolean {
  return /^[A-Za-z0-9_-]{16,128}$/.test(token);
}
// Coach links that are public (printed in db/seed.sql and the sample fixture of this public repo) can view but never
// upload or assign: otherwise anyone could spend the parser key or swap the demo client's workout before a call.
// Add more with READ_ONLY_COACH_TOKENS (comma-separated).
const PUBLIC_DEMO_COACH_TOKENS = ['demo-tristan-R7mQ2vK9xL4pN8sW1tY3aB5c'];
export function readOnlyCoachToken(token: string): boolean {
  const extra = (process.env.READ_ONLY_COACH_TOKENS ?? '').split(',').map(s => s.trim()).filter(Boolean);
  return [...PUBLIC_DEMO_COACH_TOKENS, ...extra].includes(token);
}
export const READ_ONLY_MESSAGE = 'This is the public demo coach link, so it is view-only. Use your own private coach link to upload or assign.';
export async function authorizedCoach<T>(store: ProgramStore<T>, token: string) {
  if (!validToken(token)) throw new WorkflowError('This coach link is invalid.');
  if (readOnlyCoachToken(token)) throw new WorkflowError(READ_ONLY_MESSAGE);
  const coach = await store.coach(token);
  if (!coach) throw new WorkflowError('This coach link is invalid.');
  return coach;
}
export async function uploadProgram<T>(store: ProgramStore<T>, parse: (bytes: Uint8Array) => Promise<T>, token: string, file: FormDataEntryValue | null): Promise<ActionState> {
  let uploadedPath: string | null = null;
  let saveAttempted = false;
  try {
    const coach = await authorizedCoach(store, token);
    if (!(file instanceof File) || file.size < 8 || file.size > MAX_UPLOAD_BYTES) {
      throw new WorkflowError('Choose a PDF between 8 bytes and 3 MB.');
    }
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (new TextDecoder().decode(bytes.slice(0, 5)) !== '%PDF-') {
      throw new WorkflowError('Choose a valid PDF document.');
    }
    const path = `${coach.id}/${crypto.randomUUID()}.pdf`;
    await store.upload(path, bytes);
    uploadedPath = path;
    const parsed = await parse(bytes);
    saveAttempted = true;
    await store.save(token, path, parsed);
    return { ok: true, message: 'Program saved. Review the days below, then assign one to a client.' };
  } catch (error) {
    if (saveAttempted) return { ok: false, message: 'Save confirmation was interrupted. Refresh the program library before retrying. The private PDF was retained to protect a possibly saved program.' };
    if (uploadedPath) {
      try { await store.remove(uploadedPath); } catch {
        return { ok: false, message: 'Program could not be saved and its private PDF could not be removed. Contact your administrator before retrying.' };
      }
    }
    return { ok: false, message: error instanceof WorkflowError ? error.message : 'Program could not be saved. Check the parser and database configuration, then retry.' };
  }
}
export async function assignProgramDay<T>(store: ProgramStore<T>, token: string, clientId: FormDataEntryValue | null, dayId: FormDataEntryValue | null): Promise<ActionState> {
  try {
    await authorizedCoach(store, token);
    const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (typeof clientId !== 'string' || typeof dayId !== 'string' || !uuid.test(clientId) || !uuid.test(dayId)) {
      throw new WorkflowError('Choose a client and a program day.');
    }
    // The transactional RPC revalidates both relational ownerships under a client lock.
    await store.assign(token, clientId, dayId);
    return { ok: true, message: 'Day assigned. Brodie will load it when the client starts their next call.' };
  } catch (error) {
    return { ok: false, message: error instanceof WorkflowError ? error.message : 'Assignment could not be saved. Confirm this client and day belong to your coach account, then retry.' };
  }
}
