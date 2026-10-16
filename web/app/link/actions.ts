'use server';

import { linkEmail, mayEmailLink } from '@/lib/coach-emails';
import { sendEmail } from '@/lib/email';
import { coachLink, siteOrigin } from '@/lib/site-url';
import { supabaseServer } from '@/lib/supabase/server';

export type LinkState = { ok: boolean; message: string };

const EMAIL_RE = /^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,24}$/;
// Same answer whether or not the email has an account, so this page can't be used to find out who coaches with Brodie.
const SENT = "If that email has a Brodie coach account, we just sent its link. Check your inbox (and spam) in a minute.";

export async function emailLinkAction(_prev: LinkState, form: FormData): Promise<LinkState> {
  if (String(form.get('website') ?? '')) return { ok: true, message: SENT }; // honeypot
  const email = String(form.get('email') ?? '').trim().toLowerCase();
  if (!EMAIL_RE.test(email)) return { ok: false, message: 'Enter the email you applied with.' };
  try {
    const db = supabaseServer();
    const hourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    const [{ data: coaches, error }, { count }] = await Promise.all([
      db.from('coaches').select('id,name,share_token,status,link_emailed_at').ilike('email', email).neq('status', 'rejected').limit(5),
      db.from('coaches').select('id', { count: 'exact', head: true }).gte('link_emailed_at', hourAgo),
    ]);
    if (error) return { ok: false, message: 'Could not check that right now. Please try again in a minute.' };
    const due = (coaches ?? []).filter((c) => mayEmailLink(c.link_emailed_at, count ?? 0));
    if (due.length) {
      const origin = await siteOrigin();
      const sent = await sendEmail({ to: email, ...linkEmail(due.map((c) => ({ name: c.name, link: coachLink(origin, c.share_token) }))) });
      if (sent) await db.from('coaches').update({ link_emailed_at: new Date().toISOString() }).in('id', due.map((c) => c.id));
    }
  } catch {
    return { ok: false, message: 'Could not check that right now. Please try again in a minute.' };
  }
  return { ok: true, message: SENT };
}
