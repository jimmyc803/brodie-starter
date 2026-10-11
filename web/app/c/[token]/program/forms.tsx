'use client';
import { useActionState } from 'react';
import { assignAction, uploadAction } from './actions';
import { MAX_UPLOAD_BYTES } from '@/lib/programWorkflow';
const initial = { ok: false, message: '' };
const control = 'mt-2 block w-full rounded-xl border border-slate-200 bg-white p-3 text-sm';
const button = 'mt-5 rounded-full bg-teal-800 px-6 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50';
function Status({ state }: { state: typeof initial }) {
  return state.message ? <p role={state.ok ? 'status' : 'alert'} className={`mt-4 text-sm ${state.ok ? 'text-teal-800' : 'text-red-700'}`}>{state.message}</p> : null;
}
export function UploadForm({ token }: { token: string }) {
  const [state, action, pending] = useActionState(uploadAction.bind(null, token), initial);
  return <form action={action}>
    <label className="text-sm font-medium" htmlFor="program-pdf">Program PDF</label>
    <input className={control} id="program-pdf" name="pdf" type="file" accept="application/pdf,.pdf" required disabled={pending} onChange={event => { const file = event.currentTarget.files?.[0]; event.currentTarget.setCustomValidity(file && file.size > MAX_UPLOAD_BYTES ? 'Choose a PDF no larger than 3 MB.' : ''); event.currentTarget.reportValidity(); }} />
    <p className="mt-2 text-xs text-slate-500">Up to 3 MB. Your PDF stays private. Parsing usually takes a few seconds.</p>
    <button className={button} disabled={pending}>{pending ? 'Reading your program…' : 'Upload & parse program'}</button>
    <Status state={state} />
  </form>;
}
export function AssignForm({ token, clients, days, hasPrograms }: { hasPrograms: boolean; token: string; clients: { id: string; name: string }[]; days: { id: string; label: string }[] }) {
  const [state, action, pending] = useActionState(assignAction.bind(null, token), initial);
  const unavailable = !clients.length || !days.length;
  return <form action={action}>
    <label className="text-sm font-medium" htmlFor="client-id">Client</label>
    <select id="client-id" className={control} name="client_id" defaultValue="" required disabled={pending || unavailable}>
      <option value="" disabled>Choose a client</option>{clients.map(client => <option key={client.id} value={client.id}>{client.name}</option>)}
    </select>
    <label className="mt-4 block text-sm font-medium" htmlFor="day-id">Training day</label>
    <select id="day-id" className={control} name="day_id" defaultValue="" required disabled={pending || unavailable}>
      <option value="" disabled>Choose a day</option>{days.map(day => <option key={day.id} value={day.id}>{day.label}</option>)}
    </select>
    <p className="mt-2 text-xs text-slate-500">Replaces the client&apos;s active assignment for their next call.</p>
    {unavailable && <p className="mt-3 text-sm text-slate-600">{!clients.length ? 'Add a client to this coach account to assign a day.' : hasPrograms ? 'Your programs have no countable training days. Upload a program with squats, pushups, lunges, jumping jacks, bicep curls, or pull-ups with sets and reps.' : 'Upload a program to make training days available.'}</p>}
    <button className={button} disabled={pending || unavailable}>{pending ? 'Assigning…' : 'Assign training day'}</button><Status state={state} />
  </form>;
}
