'use client';
import { useActionState } from 'react';
import { addClientAction } from './client-actions';
const initial = { ok: false, message: '' };
export function AddClientForm({ token }: { token: string }) {
  const [state, action, pending] = useActionState(addClientAction.bind(null, token), initial);
  return <form action={action}>
    <label htmlFor="new-client-name" className="text-sm font-medium text-zinc-200">Client name</label>
    <input id="new-client-name" name="client_name" required maxLength={60} autoComplete="off" disabled={pending} className="mt-2 block w-full rounded-xl border border-zinc-700 bg-zinc-950 p-3 text-sm text-zinc-100 disabled:opacity-60" />
    <button disabled={pending} className="mt-4 rounded-full border border-zinc-600 px-5 py-2.5 text-sm font-medium text-zinc-100 hover:bg-zinc-800 disabled:opacity-50">{pending ? 'Adding client…' : 'Add client'}</button>
    {state.message && <p role={state.ok ? 'status' : 'alert'} className={`mt-3 text-sm ${state.ok ? 'text-green-400' : 'text-red-400'}`}>{state.message}</p>}
  </form>;
}
