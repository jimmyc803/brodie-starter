import { Suspense } from 'react';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { supabaseServer } from '@/lib/supabase/server';
import { readOnlyCoachToken, READ_ONLY_MESSAGE, validToken } from '@/lib/programWorkflow';
import { currentAssignments } from '@/lib/currentAssignments';
import type { ProgramExercise } from '@/lib/parseProgram';
import { UploadForm, AssignForm } from './forms';
import { Surface } from '@/components/ui/apple';
import { SiteHeader } from '@/components/site-header';

export const metadata = { title: 'Training programs | Brodie', robots: { index: false, follow: false }, referrer: 'no-referrer' as const };
export const maxDuration = 90;
type Day = { id: string; program_id: string; day_number: number; title: string; exercises: ProgramExercise[] };

function Shell({ context, children }: { context?: React.ReactNode; children: React.ReactNode }) {
  return <>
    <SiteHeader context={context} />
    <div className="mx-auto max-w-[980px] px-5 pb-16 pt-10 sm:px-6">{children}</div>
  </>;
}
function Notice({ children, alert }: { children: React.ReactNode; alert?: boolean }) {
  return <Shell><h1 className="t-display text-ink">Programs</h1><Surface as="div" className="mt-8 p-6"><p role={alert ? 'alert' : undefined} className="t-body text-ink-2">{children}</p></Surface></Shell>;
}

async function ProgramContent({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  if (!validToken(token)) notFound();
  let db;
  try { db = supabaseServer(); } catch {
    return <Notice>Program service is not configured yet. Add the server credentials to enable uploads and assignments.</Notice>;
  }
  const coachResult = await db.from('coaches').select('id,name').eq('share_token', token).maybeSingle();
  if (coachResult.error) return <Notice alert>Program service is temporarily unavailable. Please retry.</Notice>;
  const coach = coachResult.data;
  if (!coach) notFound();
  const [clientsResult, programsResult] = await Promise.all([
    db.from('clients').select('id,name').eq('coach_id', coach.id).order('name'),
    db.from('programs').select('id,title,created_at').eq('coach_id', coach.id).order('created_at', { ascending: false }),
  ]);
  if (clientsResult.error || programsResult.error) return <Notice alert>Your programs could not be loaded. Please retry.</Notice>;
  const clients = clientsResult.data ?? [];
  const programs = programsResult.data ?? [];
  let days: Day[] = [];
  if (programs.length) {
    const result = await db.from('program_days').select('id,program_id,day_number,title,exercises').in('program_id', programs.map(p => p.id)).order('day_number');
    if (result.error) return <Notice alert>Your training days could not be loaded. Please retry.</Notice>;
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
  const assignable = days.filter(d => d.exercises.some(e => e.supported && e.exercise_key && e.reps > 0 && e.sets > 0)).map(d => ({ id: d.id, label: `${titles.get(d.program_id)} · Day ${d.day_number}: ${d.title}` }));
  return <Shell context={<Link href={`/c/${encodeURIComponent(token)}`} className="hover:text-ink">← Coach {coach.name}</Link>}>
    <header className="mb-8"><h1 className="t-display text-ink">Programs</h1><p className="mt-2 max-w-2xl t-body text-ink-2">Upload a program PDF, check the days Brodie read from it, then pick what each client trains on their next call.</p>{readOnlyCoachToken(token) ? <p role="note" className="mt-4 max-w-2xl rounded-[14px] bg-fill px-4 py-3 t-callout text-warning">{READ_ONLY_MESSAGE}</p> : null}</header>
    <div className="grid gap-5 md:grid-cols-2">
      <Surface as="section" className="p-6"><p className="t-footnote text-ink-3">Step 1</p><h2 className="mb-5 mt-0.5 t-title-2 text-ink">Upload a program</h2><UploadForm token={token} /></Surface>
      <Surface as="section" className="p-6"><p className="t-footnote text-ink-3">Step 2</p><h2 className="mb-5 mt-0.5 t-title-2 text-ink">Assign the next session</h2><AssignForm token={token} hasPrograms={programs.length > 0} clients={clients} days={assignable} /></Surface>
    </div>
    <section aria-labelledby="current-assignments"><Surface as="div" className="mt-5 p-6">
      <h2 id="current-assignments" className="t-title-2 text-ink">Current assignments</h2>
      <p className="mt-0.5 t-callout text-ink-2">The training day each client will load on their next call.</p>
      {assignmentError ? <p role="alert" className="mt-4 t-callout text-critical">Current assignments could not be loaded. Refresh to retry.</p>
        : current.length ? <ul className="mt-4 divide-y divide-hairline">{current.map(client => <li key={client.id} className="flex flex-col gap-1 py-3 sm:flex-row sm:justify-between sm:gap-6"><span className="t-headline text-ink">{client.name}</span><span className="t-callout text-ink-2">{client.assignment}</span></li>)}</ul>
          : <p className="mt-4 t-callout text-ink-2">No clients yet. Add a client to this coach account to assign a day.</p>}
    </Surface></section>
    <section className="mt-12"><h2 className="t-title text-ink">Program library</h2><p className="mt-1 max-w-3xl t-callout text-ink-2">Review the parsed prescriptions before assigning. Manual exercises stay in the plan; Brodie counts supported movements. Days with only manual exercises cannot be assigned to a Brodie call.</p>
      {!programs.length && <div className="mt-5 rounded-[18px] border border-dashed border-hairline p-10 text-center t-callout text-ink-2">Your first training plan starts with a PDF.</div>}
      {programs.map(program => <article key={program.id} className="mt-6"><h3 className="t-title-2 text-ink">{program.title}</h3><div className="mt-4 grid gap-5 lg:grid-cols-3">{days.filter(d => d.program_id === program.id).map(day => <div key={day.id}><p className="mb-2 px-1 t-footnote text-ink-2">Day {day.day_number} · {day.title}</p><Surface as="div" className="overflow-hidden"><ul className="divide-y divide-hairline">{day.exercises.map((exercise, i) => <li key={i} className="px-4 py-3"><div className="flex items-start justify-between gap-3"><span className="t-headline text-ink">{exercise.name}</span><span className="shrink-0 t-callout tabular-nums text-ink-2">{exercise.sets} × {exercise.reps === 0 ? 'timed' : exercise.reps}</span></div><span className={`mt-1 inline-block t-caption ${exercise.supported ? 'text-positive' : 'text-ink-2'}`}>{exercise.supported ? 'Brodie counts' : 'Manual tracking'}</span>{exercise.notes && <p className="mt-1 t-footnote text-ink-3">{exercise.notes}</p>}</li>)}</ul></Surface></div>)}</div></article>)}
    </section>
  </Shell>;
}
export default function ProgramPage({ params }: { params: Promise<{ token: string }> }) {
  return <main className="min-h-screen bg-canvas text-ink"><Suspense fallback={<p role="status" className="p-6 text-ink-2">Loading your training programs…</p>}><ProgramContent params={params} /></Suspense></main>;
}
