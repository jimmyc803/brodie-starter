'use client';
import { useActionState } from 'react';
import { addClientAction } from './client-actions';
const initial = { ok: false, message: '' };
export function AddClientForm({ token }: { token: string }) {
  const [state, action, pending] = useActionState(addClientAction.bind(null, token), initial);
  return <form action={action}>
    <label htmlFor="new-client-name" className="text-sm font-medium text-ink">Client name</label>
    <input id="new-client-name" name="client_name" required maxLength={60} autoComplete="off" disabled={pending} className="mt-2 block w-full rounded-[10px] border border-line-strong bg-surface p-3 text-sm text-ink disabled:opacity-60" />
    <button disabled={pending} className="mt-4 rounded-[10px] border border-line-strong px-5 py-2.5 text-sm font-semibold text-ink transition-colors hover:bg-sunken disabled:opacity-50">{pending ? 'Adding client…' : 'Add client'}</button>
    {state.message && <p role={state.ok ? 'status' : 'alert'} className={`mt-3 text-sm ${state.ok ? 'text-good' : 'text-bad'}`}>{state.message}</p>}
  </form>;
}
