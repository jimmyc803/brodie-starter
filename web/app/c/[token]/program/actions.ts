'use server';
import { revalidatePath } from 'next/cache';
import { consumeProgramBudget } from '@/lib/programBudget';
import { parseProgram, ProgramParseError } from '@/lib/parseProgram';
import { parserFailureMessage } from '@/lib/programSupport';
import { programStore } from '@/lib/programStore';
import { assignProgramDay, uploadProgram, WorkflowError, type ActionState } from '@/lib/programWorkflow';

export async function uploadAction(token: string, _previous: ActionState, form: FormData): Promise<ActionState> {
  let state: ActionState;
  try { state = await uploadProgram(programStore(), async bytes => {
    await consumeProgramBudget('parser');
    try { return await parseProgram(bytes); }
    catch (error) {
      if (error instanceof ProgramParseError) throw new WorkflowError(parserFailureMessage(error.code));
      throw error;
    }
  }, token, form.get('pdf')); }
  catch { return { ok: false, message: 'Program service is not configured yet. Please try again once setup is complete.' }; }
  if (state.ok) revalidatePath(`/c/${encodeURIComponent(token)}/program`);
  return state;
}
export async function assignAction(token: string, _previous: ActionState, form: FormData): Promise<ActionState> {
  let state: ActionState;
  try { state = await assignProgramDay(programStore(), token, form.get('client_id'), form.get('day_id')); }
  catch { return { ok: false, message: 'Program service is not configured yet. Please try again once setup is complete.' }; }
  if (state.ok) revalidatePath(`/c/${encodeURIComponent(token)}/program`);
  return state;
}
