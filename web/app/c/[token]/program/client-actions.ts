'use server';
import { revalidatePath } from 'next/cache';
import { createClientForCoach } from '@/lib/coachWorkspace';
import { workspaceStore } from '@/lib/workspaceStore';
import type { ActionState } from '@/lib/programWorkflow';

export async function addClientAction(token: string, _previous: ActionState, form: FormData): Promise<ActionState> {
  let state: ActionState;
  try { state = await createClientForCoach(workspaceStore(), token, form.get('client_name')); }
  catch { return { ok: false, message: 'Workspace service is not configured yet. Please try again once setup is complete.' }; }
  if (state.ok) {
    revalidatePath(`/c/${encodeURIComponent(token)}/program`);
    revalidatePath(`/c/${encodeURIComponent(token)}`);
  }
  return state;
}
