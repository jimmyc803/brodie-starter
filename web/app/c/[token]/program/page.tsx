import { Suspense } from 'react';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { supabaseServer } from '@/lib/supabase/server';
import { validToken } from '@/lib/programWorkflow';
import { currentAssignments } from '@/lib/currentAssignments';
import type { ProgramExercise } from '@/lib/parseProgram';
import { UploadForm, AssignForm } from './forms';

export const metadata = { title: 'Training programs | Brodie', robots: { index: false, follow: false }, referrer: 'no-referrer' as const };
export const maxDuration = 90;
type Day = { id: string; program_id: string; day_number: number; title: string; exercises: ProgramExercise[] };

async function ProgramContent({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  if (!validToken(token)) notFound();
  let db;
  try { db = supabaseServer(); } catch {
    return <p className="rounded-2xl border bg-white p-8">Program service is not configured yet. Add the server credentials to enable uploads and assignments.</p>;
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
  return <>
    <Link href={`/c/${encodeURIComponent(token)}`} className="text-sm text-teal-800 hover:underline">← Coach dashboard</Link>
    <header className="my-8"><p className="text-xs font-semibold uppercase tracking-[.2em] text-teal-700">Brodie for coaches / {coach.name}</p><h1 className="mt-3 text-4xl font-semibold tracking-tight">A plan. A day. A stronger client.</h1><p className="mt-4 max-w-2xl text-slate-600">Turn your program into guided training. Upload a PDF, review its days, and choose what your client trains next.</p></header>
    <div className="grid gap-6 md:grid-cols-2">
      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm"><p className="text-xs font-semibold text-teal-700">01 / BUILD THE PLAN</p><h2 className="mb-6 mt-2 text-xl font-semibold">Upload your program</h2><UploadForm token={token} /></section>
      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm"><p className="text-xs font-semibold text-teal-700">02 / MAKE IT PERSONAL</p><h2 className="mb-6 mt-2 text-xl font-semibold">Assign the next session</h2><AssignForm token={token} hasPrograms={programs.length > 0} clients={clients} days={days.filter(d => d.exercises.some(e => e.supported && e.exercise_key && e.reps > 0 && e.sets > 0)).map(d => ({ id: d.id, label: `${titles.get(d.program_id)} · Day ${d.day_number}: ${d.title}` }))} /></section>
    </div>
    <section aria-labelledby="current-assignments-title" className="mt-8 rounded-3xl border border-slate-200 bg-white p-6">
      <h2 id="current-assignments-title" className="text-xl font-semibold">Current assignments</h2>
      <p className="mt-2 text-sm text-slate-500">The training day each client will load on their next call.</p>
      {assignmentError ? <p role="alert" className="mt-4 text-sm text-red-700">Current assignments could not be loaded. Refresh to retry.</p>
        : current.length ? <ul className="mt-5 divide-y divide-slate-100">{current.map(client => <li key={client.id} className="flex flex-col gap-1 py-3 sm:flex-row sm:justify-between sm:gap-6"><span className="font-medium">{client.name}</span><span className="text-sm text-slate-600">{client.assignment}</span></li>)}</ul>
          : <p className="mt-4 text-sm text-slate-600">No clients yet. Add a client to this coach account to assign a day.</p>}
    </section>
    <section className="mt-12"><h2 className="text-2xl font-semibold">Your program library</h2><p className="mt-2 text-sm text-slate-500">Review the parsed prescriptions before assigning. Manual exercises stay in the plan; Brodie counts supported movements. Days with only manual exercises cannot be assigned to a Brodie call.</p>
      {!programs.length && <div className="mt-5 rounded-2xl border border-dashed border-slate-300 p-10 text-center text-slate-500">Your first training plan starts with a PDF.</div>}
      {programs.map(program => <article key={program.id} className="mt-6 rounded-3xl border border-slate-200 bg-white p-6"><h3 className="text-xl font-semibold">{program.title}</h3><div className="mt-5 grid gap-5 lg:grid-cols-3">{days.filter(d => d.program_id === program.id).map(day => <div key={day.id} className="rounded-2xl bg-slate-50 p-4"><p className="text-xs font-semibold uppercase tracking-wider text-teal-700">Day {day.day_number}</p><h4 className="mt-1 font-semibold">{day.title}</h4><ul className="mt-4 space-y-4">{day.exercises.map((exercise, i) => <li key={i} className="text-sm"><div className="flex items-start justify-between gap-3"><span className="font-medium">{exercise.name}</span><span className="shrink-0 text-slate-600">{exercise.sets} × {exercise.reps === 0 ? 'timed' : exercise.reps}</span></div><span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-xs ${exercise.supported ? 'bg-teal-100 text-teal-900' : 'bg-amber-100 text-amber-900'}`}>{exercise.supported ? 'Brodie counts' : 'Manual tracking'}</span>{exercise.notes && <p className="mt-1 text-xs leading-relaxed text-slate-500">{exercise.notes}</p>}</li>)}</ul></div>)}</div></article>)}
    </section>
  </>;
}
export default function ProgramPage({ params }: { params: Promise<{ token: string }> }) {
  return <main className="min-h-screen bg-slate-50 px-5 py-10 text-slate-900"><div className="mx-auto max-w-6xl"><Suspense fallback={<p role="status">Loading your training programs…</p>}><ProgramContent params={params} /></Suspense></div></main>;
}
