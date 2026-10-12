'use server';
import { revalidatePath } from 'next/cache';

import { readOnlyCoachToken, READ_ONLY_MESSAGE, validToken } from '@/lib/programWorkflow';
import { supabaseServer } from '@/lib/supabase/server';

export type AddClientState = { ok: boolean; message: string; clientId?: string };

// Add a client to the coach behind this private link. The new client gets their own workout link (clients.share_token).
export async function addClientAction(token: string, _prev: AddClientState, form: FormData): Promise<AddClientState> {
  if (!validToken(token)) return { ok: false, message: 'This coach link is invalid.' };
  if (readOnlyCoachToken(token)) return { ok: false, message: READ_ONLY_MESSAGE };
  const name = String(form.get('name') ?? '').trim().replace(/\s+/g, ' ');
  if (name.length < 1 || name.length > 60) return { ok: false, message: 'Enter the client\'s name (up to 60 characters).' };
  try {
    const db = supabaseServer();
    const { data: coach } = await db.from('coaches').select('id, status').eq('share_token', token).maybeSingle();
    if (!coach) return { ok: false, message: 'This coach link is invalid.' };
    if (coach.status !== 'approved') return { ok: false, message: 'Adding clients unlocks once your coach application is approved.' };
    const { count } = await db.from('clients').select('id', { count: 'exact', head: true }).eq('coach_id', coach.id);
    if ((count ?? 0) >= 200) return { ok: false, message: 'Client limit reached for this coach.' };
    const { data: client, error } = await db.from('clients').insert({ coach_id: coach.id, name }).select('id').single();
    if (error || !client) return { ok: false, message: 'Could not add the client. Please retry.' };
    revalidatePath(`/c/${encodeURIComponent(token)}/clients`);
    return { ok: true, message: `${name} added. Assign them a day, then send their link.`, clientId: client.id as string };
  } catch {
    return { ok: false, message: 'Could not add the client. Please retry.' };
  }
}
