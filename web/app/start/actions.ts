'use server';
import { redirect } from 'next/navigation';

import { alertNewCoach } from '@/lib/coach-alert';
import { welcomeEmail } from '@/lib/coach-emails';
import { sendEmail } from '@/lib/email';
import { coachLink, siteOrigin } from '@/lib/site-url';
import { supabaseServer } from '@/lib/supabase/server';

export type SignupState = { ok: boolean; message: string };

const EMAIL_RE = /^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,24}$/;
const MIN_FILL_MS = 2500; // humans take longer than this to fill the form; most bots don't
const MAX_PER_EMAIL = 3;
const MAX_PER_HOUR = 40; // flood guard for the whole site
const CLIENT_BUCKETS = ['1-5', '6-15', '16-40', '40+'];
const clip = (v: FormDataEntryValue | null, n: number) => String(v ?? '').trim().replace(/\s+/g, ' ').slice(0, n);

// A coach application from /start: the coach is created 'pending' (sandbox: demo client, program upload) and lands on their
// private dashboard; the team approves them in /admin, which unlocks real clients and workout links.
export async function signupAction(_prev: SignupState, form: FormData): Promise<SignupState> {
  if (String(form.get('website') ?? '')) return { ok: false, message: 'Something went wrong. Please try again.' }; // honeypot
  const started = Number(form.get('started') ?? 0);
  if (!started || Date.now() - started < MIN_FILL_MS) return { ok: false, message: 'Please take a second to fill in the form, then try again.' };

  const name = String(form.get('name') ?? '').trim().replace(/\s+/g, ' ').replace(/^coach\s+/i, '');
  const email = String(form.get('email') ?? '').trim().toLowerCase();
  const instagram = String(form.get('instagram') ?? '').trim().replace(/^@/, '').slice(0, 60) || null;
  const website = clip(form.get('site'), 200) || null;
  const where = clip(form.get('where'), 120);
  const clients = String(form.get('clients') ?? '');
  const certification = clip(form.get('certification'), 120) || null;
  const note = clip(form.get('note'), 500) || null;
  if (name.length < 1 || name.length > 60) return { ok: false, message: 'Enter your name (up to 60 characters).' };
  if (!EMAIL_RE.test(email)) return { ok: false, message: 'Enter a valid email so we can reach you about your application.' };
  if (!where) return { ok: false, message: 'Tell us where you coach (a gym, a studio, or online).' };
  if (!CLIENT_BUCKETS.includes(clients)) return { ok: false, message: 'Pick roughly how many clients you coach.' };
  if (!instagram && !website) return { ok: false, message: 'Add your Instagram or website so we can see your coaching.' };

  let token: string;
  try {
    const db = supabaseServer();
    const hourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    const [{ count: perEmail }, { count: lastHour }] = await Promise.all([
      db.from('coaches').select('id', { count: 'exact', head: true }).ilike('email', email),
      db.from('coaches').select('id', { count: 'exact', head: true }).eq('signup_source', 'web').gte('created_at', hourAgo),
    ]);
    if ((perEmail ?? 0) >= MAX_PER_EMAIL) return { ok: false, message: 'This email already has a coach account. Use "Email me my link" below to get it again.' };
    if ((lastHour ?? 0) >= MAX_PER_HOUR) return { ok: false, message: 'Lots of sign-ups right now. Please try again in a few minutes.' };
    const application = { where, clients, website, certification, note, applied_at: new Date().toISOString() };
    const { data, error } = await db
      .from('coaches')
      .insert({ name, email, instagram, signup_source: 'web', status: 'pending', application })
      .select('share_token')
      .single();
    if (error || !data) return { ok: false, message: 'Could not create your account. Please try again.' };
    token = data.share_token as string;
  } catch {
    return { ok: false, message: 'Could not create your account. Please try again.' };
  }
  const link = coachLink(await siteOrigin(), token);
  await Promise.all([sendEmail({ to: email, ...welcomeEmail({ name, link }) }), alertNewCoach([
    `New coach application: ${name} (${email})`,
    `Coaches at: ${where} · clients: ${clients}`,
    instagram ? `Instagram: https://instagram.com/${instagram}` : '',
    website ? `Website: ${website}` : '',
    certification ? `Certification: ${certification}` : '',
    note ? `Note: ${note}` : '',
    'Review it in /admin.',
  ].filter(Boolean))]);
  redirect(`/c/${encodeURIComponent(token)}?welcome=1`);
}
