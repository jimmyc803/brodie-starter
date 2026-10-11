import { Suspense } from 'react';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { supabaseServer } from '@/lib/supabase/server';
import { readOnlyCoachToken, READ_ONLY_MESSAGE, validToken } from '@/lib/programWorkflow';
import { currentAssignments } from '@/lib/currentAssignments';
import type { ProgramExercise } from '@/lib/parseProgram';
import { UploadForm, AssignForm } from './forms';
import { AddClientForm } from './client-form';
import { ExerciseSupport } from './exercise-support';
import { exerciseReviewBrief, supportBookingUrl } from '@/lib/programSupport';
import { SiteHeader } from '@/components/site-header';

export const metadata = { title: 'Training programs | Brodie', robots: { index: false, follow: false }, referrer: 'no-referrer' as const };
export const maxDuration = 90;
type Day = { id: string; program_id: string; day_number: number; title: string; exercises: ProgramExercise[] };

async function ProgramContent({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  if (!validToken(token)) notFound();
  let db;
  try { db = supabaseServer(); } catch {
    return <p className="rounded-2xl border border-zinc-800 bg-zinc-900 p-8">Program service is not configured yet. Add the server credentials to enable uploads and assignments.</p>;
  }
  const coachResult = await db.from('coaches').select('id,name').eq('share_token', token).maybeSingle();
  if (coachResult.error) return <p role="alert">Program service is temporarily unavailable. Please retry.</p>;
  const coach = coachResult.data;
  if (!coach) notFound();
  const [clientsResult, programsResult] = await Promise.all([
    db.from('clients').select('id,name').eq('coach_id', coach.id).order('name'),
    db.from('programs').select('id,title,created_at').eq('coach_id', coach.id).order('created_at', { ascending: false }),
  ]);
  if (clientsResult.error || programsResult.error) return <p role="alert">Your programs could not be loaded. Please retry.</p>;
  const clients = clientsResult.data ?? [];
  const programs = programsResult.data ?? [];
  let days: Day[] = [];
  if (programs.length) {
    const result = await db.from('program_days').select('id,program_id,day_number,title,exercises').in('program_id', programs.map(p => p.id)).order('day_number');
    if (result.error) return <p role="alert">Your training days could not be loaded. Please retry.</p>;
    days = result.data as Day[];
  }
  let assignments: unknown[] = [];
  let assignmentError = false;
  if (clients.length) {
    const result = await db.from('assignments').select('client_id,program_day_id,assigned_at,active')
      .in('client_id', clients.map(client => client.id)).eq('active', true).order('assigned_at', { ascending: false });
    assignmentError = Boolean(result.error);
    assignments = result.data ?? [];
  }
  const titles = new Map(programs.map(p => [p.id, p.title]));
  const dayLabels = days.map(day => ({ id: day.id, label: `${titles.get(day.program_id)} · Day ${day.day_number}: ${day.title}` }));
  const current = currentAssignments(clients, dayLabels, assignments);
  const readOnly = readOnlyCoachToken(token);
  const supportBrief = exerciseReviewBrief(programs.map(program => ({ title: program.title, days: days.filter(day => day.program_id === program.id) })));
  const bookingUrl = supportBookingUrl(process.env.COACH_SUPPORT_BOOKING_URL);
  return <>
    <SiteHeader context={<Link href={`/c/${encodeURIComponent(token)}`} className="hover:text-zinc-100">← Coach {coach.name}</Link>} />
    <header className="mb-8 mt-8"><h1 className="text-3xl font-bold tracking-tight text-zinc-50">Programs</h1><p className="mt-1 max-w-2xl text-sm text-zinc-400">Upload a program PDF, check the days Brodie read from it, then pick what each client trains on their next call.</p>{readOnly ? <p role="note" className="mt-4 max-w-2xl rounded-xl border border-yellow-400/20 bg-yellow-400/10 px-4 py-3 text-sm text-yellow-100">{READ_ONLY_MESSAGE} <Link href="/coach/start" className="mt-3 block w-fit rounded-full bg-zinc-50 px-4 py-2 font-medium text-zinc-950">Create private workspace</Link></p> : <p className="mt-3 text-xs text-zinc-500">Bookmark this private coach link. Anyone with it can manage your programs and clients.</p>}</header>
    {!readOnly && <><div className="grid gap-6 md:grid-cols-2">
      <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-6"><p className="text-sm text-zinc-500">Step 1</p><h2 className="mb-5 mt-0.5 text-lg font-semibold text-zinc-50">Upload a program</h2><UploadForm token={token} /></section>
      <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-6"><p className="text-sm text-zinc-500">Step 2</p><h2 className="mb-5 mt-0.5 text-lg font-semibold text-zinc-50">Assign the next session</h2><AssignForm token={token} hasPrograms={programs.length > 0} clients={clients} days={days.filter(d => d.exercises.some(e => e.supported && e.exercise_key && e.reps > 0 && e.sets > 0)).map(d => ({ id: d.id, label: `${titles.get(d.program_id)} · Day ${d.day_number}: ${d.title}` }))} /></section>
    </div><section className="mt-6 rounded-2xl border border-zinc-800 bg-zinc-900 p-6"><h2 className="text-lg font-semibold">Add a client</h2><p className="mb-4 mt-1 text-sm text-zinc-400">Create a client here, then choose their next training day above.</p><AddClientForm token={token} /></section></>}
    <section aria-labelledby="current-assignments-title" className="mt-6 rounded-2xl border border-zinc-800 bg-zinc-900 p-6">
      <h2 id="current-assignments-title" className="text-lg font-semibold text-zinc-50">Current assignments</h2>
      <p className="mt-0.5 text-sm text-zinc-500">The training day each client will load on their next call.</p>
      {assignmentError ? <p role="alert" className="mt-4 text-sm text-red-400">Current assignments could not be loaded. Refresh to retry.</p>
        : current.length ? <ul className="mt-5 divide-y divide-zinc-800">{current.map(client => <li key={client.id} className="flex flex-col gap-1 py-3 sm:flex-row sm:justify-between sm:gap-6"><span className="font-medium text-zinc-100">{client.name}</span><span className="text-sm text-zinc-400">{client.assignment}</span></li>)}</ul>
          : <p className="mt-4 text-sm text-zinc-400">No clients yet. Add a client to this coach account to assign a day.</p>}
    </section>
    <section className="mt-10"><h2 className="text-lg font-semibold text-zinc-50">Program library</h2><p className="mt-0.5 max-w-3xl text-sm text-zinc-500">Review each exercise, set, rep and note against your PDF before assigning. Every exercise stays in your program. During a call, Brodie tracks only supported movements; exercises marked “No video tracking” are omitted from the automated workout. Days with no tracked exercises stay in your library but cannot be assigned to a video call.</p>
      {!programs.length && <div className="mt-5 rounded-2xl border border-dashed border-zinc-800 p-10 text-center text-zinc-500">Your first training plan starts with a PDF.</div>}
      {programs.map(program => <article key={program.id} className="mt-4 rounded-2xl border border-zinc-800 bg-zinc-900 p-6"><h3 className="text-lg font-semibold text-zinc-50">{program.title}</h3><div className="mt-5 grid gap-5 lg:grid-cols-3">{days.filter(d => d.program_id === program.id).map(day => <div key={day.id} className="rounded-xl border border-zinc-800 bg-zinc-950/40 p-4"><p className="text-xs text-zinc-500">Day {day.day_number}</p><h4 className="mt-0.5 font-semibold text-zinc-100">{day.title}</h4><ul className="mt-4 space-y-4">{day.exercises.map((exercise, i) => <li key={i} className="text-sm"><div className="flex items-start justify-between gap-3"><span className="font-medium text-zinc-200">{exercise.name}</span><span className="shrink-0 tabular-nums text-zinc-400">{exercise.sets} × {exercise.reps === 0 ? 'timed' : exercise.reps}</span></div><span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-xs ${exercise.supported ? 'bg-green-500/10 text-green-300' : 'bg-zinc-800 text-zinc-400'}`}>{exercise.supported ? 'Video tracking' : 'No video tracking'}</span>{exercise.notes && <p className="mt-1 text-xs leading-relaxed text-zinc-500">{exercise.notes}</p>}</li>)}</ul></div>)}</div></article>)}
    </section>
    {supportBrief && <ExerciseSupport brief={supportBrief} bookingUrl={bookingUrl} />}
  </>;
}
export default function ProgramPage({ params }: { params: Promise<{ token: string }> }) {
  return <main className="min-h-screen bg-zinc-950 px-4 pb-12 pt-5 text-zinc-100 sm:px-6 sm:pt-8"><div className="mx-auto max-w-6xl"><Suspense fallback={<p role="status" className="text-zinc-400">Loading your training programs…</p>}><ProgramContent params={params} /></Suspense></div></main>;
}
