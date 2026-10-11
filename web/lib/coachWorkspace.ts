import { randomBytes, randomUUID } from 'node:crypto';
// @ts-expect-error Node's native TypeScript test runner requires the explicit source extension.
import { readOnlyCoachToken, validToken, READ_ONLY_MESSAGE, type ActionState } from './programWorkflow.ts';

export interface CoachWorkspaceStore {
  coach(token: string): Promise<{ id: string; name: string } | null>;
  createCoach(coach: { id: string; name: string; share_token: string }): Promise<void>;
  createClient(client: { id: string; coach_id: string; name: string; share_token: string }): Promise<void>;
  removeCoach(id: string): Promise<void>;
}
export type WorkspaceResult = { ok: true; token: string } | { ok: false; message: string };
function nameValue(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const name = value.trim();
  return name.length >= 1 && name.length <= 80 && !/[\u0000-\u001f\u007f]/.test(name) ? name : null;
}
function privateToken(): string { return randomBytes(32).toString('hex'); }

export async function createCoachWorkspace(store: CoachWorkspaceStore, coachName: unknown, clientName: unknown): Promise<WorkspaceResult> {
  const name = nameValue(coachName);
  const client = nameValue(clientName);
  if (!name || !client) return { ok: false, message: 'Enter a coach name and a first client name, each between 1 and 80 characters.' };
  const id = randomUUID();
  const token = privateToken();
  try {
    await store.createCoach({ id, name, share_token: token });
    await store.createClient({ id: randomUUID(), coach_id: id, name: client, share_token: privateToken() });
    return { ok: true, token };
  } catch {
    // Delete by our generated ID even if the first insert committed but its acknowledgement was lost.
    // The existing foreign-key cascade also removes a client whose insert committed before a network failure.
    try { await store.removeCoach(id); }
    catch { return { ok: false, message: 'Workspace setup was interrupted and cleanup could not be confirmed. Contact your administrator before retrying.' }; }
    return { ok: false, message: 'Workspace could not be created. Please try again.' };
  }
}

export async function createClientForCoach(store: CoachWorkspaceStore, token: string, clientName: unknown): Promise<ActionState> {
  if (typeof token !== 'string' || !validToken(token)) return { ok: false, message: 'This coach link is invalid.' };
  if (readOnlyCoachToken(token)) return { ok: false, message: READ_ONLY_MESSAGE };
  const name = nameValue(clientName);
  if (!name) return { ok: false, message: 'Enter a client name between 1 and 80 characters.' };
  try {
    const coach = await store.coach(token);
    if (!coach) return { ok: false, message: 'This coach link is invalid.' };
    await store.createClient({ id: randomUUID(), coach_id: coach.id, name, share_token: privateToken() });
    return { ok: true, message: 'Client added. You can now assign their next training day.' };
  } catch {
    return { ok: false, message: 'Client creation could not be confirmed. Refresh the client list before retrying.' };
  }
}
