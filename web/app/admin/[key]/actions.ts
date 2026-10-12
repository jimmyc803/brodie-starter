'use server';
import { revalidatePath } from 'next/cache';

import { isAdminKey } from '@/lib/admin';
import { supabaseServer } from '@/lib/supabase/server';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Approve or reject a coach application. Approval unlocks adding clients and sending workout links.
export async function reviewCoachAction(key: string, form: FormData): Promise<void> {
  if (!isAdminKey(key)) return;
  const id = String(form.get('id') ?? '');
  const decision = String(form.get('decision') ?? '');
  if (!UUID.test(id) || !['approved', 'rejected', 'pending'].includes(decision)) return;
  await supabaseServer().from('coaches').update({ status: decision, reviewed_at: decision === 'pending' ? null : new Date().toISOString() }).eq('id', id);
  revalidatePath(`/admin/${key}`);
}
