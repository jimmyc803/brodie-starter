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

export type ManageClientState = { ok: boolean; message: string };

// The approved coach behind this link and one of their clients, or an error message.
type Owned = { error: string } | { db: ReturnType<typeof supabaseServer>; coachId: string };
async function ownClient(token: string, clientId: string): Promise<Owned> {
  if (!validToken(token)) return { error: 'This coach link is invalid.' };
  if (readOnlyCoachToken(token)) return { error: READ_ONLY_MESSAGE };
  if (!/^[0-9a-f-]{36}$/i.test(clientId)) return { error: 'Unknown client.' };
  const db = supabaseServer();
  const { data: coach } = await db.from('coaches').select('id, status').eq('share_token', token).maybeSingle();
  if (!coach) return { error: 'This coach link is invalid.' };
  if (coach.status !== 'approved') return { error: 'Managing clients unlocks once your coach application is approved.' };
  const { data: client } = await db.from('clients').select('id').eq('id', clientId).eq('coach_id', coach.id).maybeSingle();
  if (!client) return { error: 'Unknown client.' };
  return { db, coachId: coach.id as string };
}

export async function renameClientAction(token: string, clientId: string, _prev: ManageClientState, form: FormData): Promise<ManageClientState> {
  const name = String(form.get('name') ?? '').trim().replace(/\s+/g, ' ');
  if (name.length < 1 || name.length > 60) return { ok: false, message: 'Enter the client\'s name (up to 60 characters).' };
  try {
    const own = await ownClient(token, clientId);
    if ('error' in own) return { ok: false, message: own.error };
    const { error } = await own.db.from('clients').update({ name }).eq('id', clientId).eq('coach_id', own.coachId);
    if (error) return { ok: false, message: 'Could not rename the client. Please retry.' };
    revalidatePath(`/c/${encodeURIComponent(token)}`, 'layout');
    return { ok: true, message: 'Saved.' };
  } catch {
    return { ok: false, message: 'Could not rename the client. Please retry.' };
  }
}

// Removes the client and, by cascade, their assignments, sessions and sets; recap images in storage are removed best effort.
export async function deleteClientAction(token: string, clientId: string): Promise<ManageClientState> {
  try {
    const own = await ownClient(token, clientId);
    if ('error' in own) return { ok: false, message: own.error };
    const { data: sessions } = await own.db.from('sessions').select('id').eq('client_id', clientId);
    const { error } = await own.db.from('clients').delete().eq('id', clientId).eq('coach_id', own.coachId);
    if (error) return { ok: false, message: 'Could not remove the client. Please retry.' };
    const paths = (sessions ?? []).flatMap((s) => [`${s.id}.png`, `videos/${s.id}.mp4`]);
    if (paths.length) await own.db.storage.from('recaps').remove(paths).catch(() => {});
    revalidatePath(`/c/${encodeURIComponent(token)}`, 'layout');
    return { ok: true, message: 'Removed.' };
  } catch {
    return { ok: false, message: 'Could not remove the client. Please retry.' };
  }
}
