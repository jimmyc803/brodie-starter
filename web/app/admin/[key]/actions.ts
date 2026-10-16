'use server';
import { revalidatePath } from 'next/cache';

import { isAdminKey } from '@/lib/admin';
import { approvedEmail } from '@/lib/coach-emails';
import { sendEmail } from '@/lib/email';
import { coachLink, siteOrigin } from '@/lib/site-url';
import { supabaseServer } from '@/lib/supabase/server';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Approve or reject a coach application. Approval unlocks adding clients and sending workout links, and emails the coach
// (only on the change to approved, so a second click never sends a second email).
export async function reviewCoachAction(key: string, form: FormData): Promise<void> {
  if (!isAdminKey(key)) return;
  const id = String(form.get('id') ?? '');
  const decision = String(form.get('decision') ?? '');
  if (!UUID.test(id) || !['approved', 'rejected', 'pending'].includes(decision)) return;
  const { data } = await supabaseServer()
    .from('coaches')
    .update({ status: decision, reviewed_at: decision === 'pending' ? null : new Date().toISOString() })
    .eq('id', id)
    .neq('status', decision)
    .select('name,email,share_token');
  const coach = data?.[0];
  if (decision === 'approved' && coach?.email) {
    await sendEmail({ to: coach.email, ...approvedEmail({ name: coach.name, link: coachLink(await siteOrigin(), coach.share_token) }) });
  }
  revalidatePath(`/admin/${key}`);
}
