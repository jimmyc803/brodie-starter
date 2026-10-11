'use server';
import { redirect } from 'next/navigation';
import { createCoachWorkspace, type WorkspaceResult } from '@/lib/coachWorkspace';
import { workspaceStore } from '@/lib/workspaceStore';
import type { ActionState } from '@/lib/programWorkflow';

export async function createWorkspaceAction(_previous: ActionState, form: FormData): Promise<ActionState> {
  let result: WorkspaceResult;
  try { result = await createCoachWorkspace(workspaceStore(), form.get('coach_name'), form.get('client_name')); }
  catch { return { ok: false, message: 'Workspace service is not configured yet. Please try again once setup is complete.' }; }
  if (!result.ok) return result;
  redirect(`/c/${result.token}/program`);
}
