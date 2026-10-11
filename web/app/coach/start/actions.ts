'use server';
import { redirect } from 'next/navigation';
import { createCoachWorkspace, workspaceName, type WorkspaceResult } from '@/lib/coachWorkspace';
import { workspaceStore } from '@/lib/workspaceStore';
import { consumeProgramBudget } from '@/lib/programBudget';
import { WorkflowError, type ActionState } from '@/lib/programWorkflow';

export async function createWorkspaceAction(_previous: ActionState, form: FormData): Promise<ActionState> {
  const coachName = form.get('coach_name');
  const clientName = form.get('client_name');
  if (!workspaceName(coachName) || !workspaceName(clientName)) return { ok: false, message: 'Enter a coach name and a first client name, each between 1 and 80 characters.' };
  let result: WorkspaceResult;
  try {
    await consumeProgramBudget('workspace');
    result = await createCoachWorkspace(workspaceStore(), coachName, clientName);
  }
  catch (error) { return { ok: false, message: error instanceof WorkflowError ? error.message : 'Workspace service is not configured yet. Please try again once setup is complete.' }; }
  if (!result.ok) return result;
  redirect(`/c/${result.token}/program`);
}
