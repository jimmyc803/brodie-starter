'use server';
import { redirect } from 'next/navigation';

import { supabaseServer } from '@/lib/supabase/server';

export type SignupState = { ok: boolean; message: string };

const EMAIL_RE = /^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,24}$/;
const MIN_FILL_MS = 2500; // humans take longer than this to fill the form; most bots don't
const MAX_PER_EMAIL = 3;
const MAX_PER_HOUR = 40; // flood guard for the whole site

// Create a coach from the /start form, then open their private dashboard (the link is their login).
export async function signupAction(_prev: SignupState, form: FormData): Promise<SignupState> {
  if (String(form.get('website') ?? '')) return { ok: false, message: 'Something went wrong. Please try again.' }; // honeypot
  const started = Number(form.get('started') ?? 0);
  if (!started || Date.now() - started < MIN_FILL_MS) return { ok: false, message: 'Please take a second to fill in the form, then try again.' };

  const name = String(form.get('name') ?? '').trim().replace(/\s+/g, ' ').replace(/^coach\s+/i, '');
  const email = String(form.get('email') ?? '').trim().toLowerCase();
  const instagram = String(form.get('instagram') ?? '').trim().replace(/^@/, '').slice(0, 60) || null;
  if (name.length < 1 || name.length > 60) return { ok: false, message: 'Enter your name (up to 60 characters).' };
  if (!EMAIL_RE.test(email)) return { ok: false, message: 'Enter a valid email so we can send you your link if you lose it.' };

  let token: string;
  try {
    const db = supabaseServer();
    const hourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    const [{ count: perEmail }, { count: lastHour }] = await Promise.all([
      db.from('coaches').select('id', { count: 'exact', head: true }).ilike('email', email),
      db.from('coaches').select('id', { count: 'exact', head: true }).eq('signup_source', 'web').gte('created_at', hourAgo),
    ]);
    if ((perEmail ?? 0) >= MAX_PER_EMAIL) return { ok: false, message: 'This email already has a coach account. Check your saved link, or contact us to get it again.' };
    if ((lastHour ?? 0) >= MAX_PER_HOUR) return { ok: false, message: 'Lots of sign-ups right now. Please try again in a few minutes.' };
    const { data, error } = await db.from('coaches').insert({ name, email, instagram, signup_source: 'web' }).select('share_token').single();
    if (error || !data) return { ok: false, message: 'Could not create your account. Please try again.' };
    token = data.share_token as string;
  } catch {
    return { ok: false, message: 'Could not create your account. Please try again.' };
  }
  redirect(`/c/${encodeURIComponent(token)}?welcome=1`);
}
