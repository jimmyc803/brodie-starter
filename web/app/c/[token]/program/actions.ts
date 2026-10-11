'use server';
import { revalidatePath } from 'next/cache';
import { parseProgram } from '@/lib/parseProgram';
import { programStore } from '@/lib/programStore';
import { assignProgramDay, uploadProgram, type ActionState } from '@/lib/programWorkflow';

export async function uploadAction(token: string, _previous: ActionState, form: FormData): Promise<ActionState> {
  let state: ActionState;
  try { state = await uploadProgram(programStore(), parseProgram, token, form.get('pdf')); }
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
