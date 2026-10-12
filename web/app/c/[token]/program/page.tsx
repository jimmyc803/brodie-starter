import { Suspense } from 'react';
import { notFound } from 'next/navigation';
import { supabaseServer } from '@/lib/supabase/server';
import { readOnlyCoachToken, READ_ONLY_MESSAGE, validToken } from '@/lib/programWorkflow';
import { currentAssignments } from '@/lib/currentAssignments';
import type { ProgramExercise } from '@/lib/parseProgram';
import { UploadForm, AssignForm } from './forms';
import { CoachShell } from '@/components/coach/coach-shell';

export const metadata = { title: 'Training programs | Brodie', robots: { index: false, follow: false }, referrer: 'no-referrer' as const };
export const maxDuration = 90;
type Day = { id: string; program_id: string; day_number: number; title: string; exercises: ProgramExercise[] };

async function ProgramContent({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  if (!validToken(token)) notFound();
  let db;
  try { db = supabaseServer(); } catch {
    return <p className="rounded-[14px] border border-line bg-surface p-8">Program service is not configured yet. Add the server credentials to enable uploads and assignments.</p>;
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
  return <CoachShell token={token} coachName={coach.name} active="programs">
    <header className="mb-8"><h1 className="text-[28px] font-semibold tracking-[-0.025em] text-ink">Programs</h1><p className="mt-1 max-w-2xl text-sm text-ink-2">Upload a program PDF, check the days Brodie read from it, then pick what each client trains on their next call.</p>{readOnlyCoachToken(token) ? <p role="note" className="mt-4 max-w-2xl rounded-[10px] border border-line bg-warn-soft px-4 py-3 text-sm text-warn">{READ_ONLY_MESSAGE}</p> : null}</header>
    <div className="grid gap-6 md:grid-cols-2">
      <section className="rounded-[14px] border border-line bg-surface p-6"><p className="text-sm text-ink-3">Step 1</p><h2 className="mb-5 mt-0.5 text-lg font-semibold text-ink">Upload a program</h2><UploadForm token={token} /></section>
      <section id="assign" className="scroll-mt-6 rounded-[14px] border border-line bg-surface p-6"><p className="text-sm text-ink-3">Step 2</p><h2 className="mb-5 mt-0.5 text-lg font-semibold text-ink">Assign the next session</h2><AssignForm token={token} hasPrograms={programs.length > 0} clients={clients} days={days.filter(d => d.exercises.some(e => e.supported && e.exercise_key && e.reps > 0 && e.sets > 0)).map(d => ({ id: d.id, label: `${titles.get(d.program_id)} · Day ${d.day_number}: ${d.title}` }))} /></section>
    </div>
    <section aria-labelledby="current-assignments-title" className="mt-6 rounded-[14px] border border-line bg-surface p-6">
      <h2 id="current-assignments-title" className="text-lg font-semibold text-ink">Current assignments</h2>
      <p className="mt-0.5 text-sm text-ink-3">The training day each client will load on their next call.</p>
      {assignmentError ? <p role="alert" className="mt-4 text-sm text-bad">Current assignments could not be loaded. Refresh to retry.</p>
        : current.length ? <ul className="mt-5 divide-y divide-line">{current.map(client => <li key={client.id} className="flex flex-col gap-1 py-3 sm:flex-row sm:justify-between sm:gap-6"><span className="font-medium text-ink">{client.name}</span><span className="text-sm text-ink-2">{client.assignment}</span></li>)}</ul>
          : <p className="mt-4 text-sm text-ink-2">No clients yet. Add a client to this coach account to assign a day.</p>}
    </section>
    <section className="mt-10"><h2 className="text-lg font-semibold text-ink">Program library</h2><p className="mt-0.5 max-w-3xl text-sm text-ink-3">Review the parsed prescriptions before assigning. Manual exercises stay in the plan; Brodie counts supported movements. Days with only manual exercises cannot be assigned to a Brodie call.</p>
      {!programs.length && <div className="mt-5 rounded-[14px] border border-dashed border-line-strong p-10 text-center text-ink-3">Your first training plan starts with a PDF.</div>}
      {programs.map(program => <article key={program.id} className="mt-4 rounded-[14px] border border-line bg-surface p-6"><h3 className="text-lg font-semibold text-ink">{program.title}</h3><div className="mt-5 grid gap-5 lg:grid-cols-3">{days.filter(d => d.program_id === program.id).map(day => <div key={day.id} className="rounded-[10px] border border-line bg-canvas p-4"><p className="text-xs text-ink-3">Day {day.day_number}</p><h4 className="mt-0.5 font-semibold text-ink">{day.title}</h4><ul className="mt-4 space-y-4">{day.exercises.map((exercise, i) => <li key={i} className="text-sm"><div className="flex items-start justify-between gap-3"><span className="font-medium text-ink">{exercise.name}</span><span className="shrink-0 tabular-nums text-ink-2">{exercise.sets} × {exercise.reps === 0 ? 'timed' : exercise.reps}</span></div><span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-xs ${exercise.supported ? 'bg-good-soft text-good' : 'bg-idle-soft text-ink-2'}`}>{exercise.supported ? 'Brodie counts' : 'Manual tracking'}</span>{exercise.notes && <p className="mt-1 text-xs leading-relaxed text-ink-3">{exercise.notes}</p>}</li>)}</ul></div>)}</div></article>)}
    </section>
  </CoachShell>;
}
export default function ProgramPage({ params }: { params: Promise<{ token: string }> }) {
  return <main className="flex min-h-screen flex-1 flex-col bg-canvas text-ink"><Suspense fallback={<p role="status" className="p-8 text-ink-2">Loading your training programs…</p>}><ProgramContent params={params} /></Suspense></main>;
}
