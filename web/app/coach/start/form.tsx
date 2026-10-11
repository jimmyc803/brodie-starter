'use client';
import { useActionState } from 'react';
import { createWorkspaceAction } from './actions';
const initial = { ok: false, message: '' };
const input = 'mt-2 block w-full rounded-xl border border-zinc-700 bg-zinc-950 p-3 text-sm text-zinc-100 disabled:opacity-60';
export function WorkspaceForm() {
  const [state, action, pending] = useActionState(createWorkspaceAction, initial);
  return <form action={action} className="mt-8 space-y-5">
    <div><label htmlFor="coach-name" className="text-sm font-medium">Your name</label><input id="coach-name" name="coach_name" autoComplete="name" className={input} required maxLength={80} disabled={pending} /></div>
    <div><label htmlFor="first-client-name" className="text-sm font-medium">First client&apos;s name</label><input id="first-client-name" name="client_name" autoComplete="off" className={input} required maxLength={80} disabled={pending} /><p className="mt-2 text-xs text-zinc-400">You can add more clients in your workspace.</p></div>
    <p className="text-sm leading-relaxed text-zinc-400">Your workspace uses a private link instead of a password. Anyone with that link can manage your clients and programs. Bookmark it and keep it private.</p>
    <button disabled={pending} className="rounded-full bg-zinc-50 px-5 py-3 text-sm font-medium text-zinc-950 hover:bg-zinc-200 disabled:opacity-50">{pending ? 'Creating workspace…' : 'Create private workspace'}</button>
    {state.message && <p role="alert" className="text-sm text-red-400">{state.message}</p>}
  </form>;
}
