'use server';
import { revalidatePath } from 'next/cache';
import { addClientAction as addApprovedClient } from '../clients/actions';
import type { ActionState } from '@/lib/programWorkflow';

export async function addClientAction(token: string, _previous: ActionState, form: FormData): Promise<ActionState> {
  // Both entry points must enforce the same approval, ownership and client-limit rules.
  const clientForm = new FormData();
  const name = form.get('client_name');
  if (typeof name === 'string') clientForm.set('name', name);
  const state = await addApprovedClient(token, _previous, clientForm);
  if (state.ok) {
    revalidatePath(`/c/${encodeURIComponent(token)}/program`);
    revalidatePath(`/c/${encodeURIComponent(token)}`);
  }
  return state;
}
