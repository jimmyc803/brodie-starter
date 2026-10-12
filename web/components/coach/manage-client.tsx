"use client";

import { useRouter } from "next/navigation";
import { useActionState, useState, useTransition } from "react";

import { deleteClientAction, renameClientAction, type ManageClientState } from "@/app/c/[token]/clients/actions";

// Rename / Remove for one client, next to their name in the client header (approved coaches only).
export function ManageClient({ token, clientId, name, base }: { token: string; clientId: string; name: string; base: string }) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [removing, startRemove] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [state, rename, saving] = useActionState<ManageClientState, FormData>(async (prev, form) => {
    const res = await renameClientAction(token, clientId, prev, form);
    if (res.ok) setEditing(false);
    return res;
  }, { ok: false, message: "" });

  function remove() {
    if (!window.confirm(`Remove ${name}? Their workouts and recaps are deleted too, and their link stops working.`)) return;
    setError(null);
    startRemove(async () => {
      const res = await deleteClientAction(token, clientId);
      if (res.ok) router.push(base);
      else setError(res.message);
    });
  }

  if (editing)
    return (
      <form action={rename} className="flex w-full flex-wrap items-center gap-2">
        <input
          name="name"
          defaultValue={name}
          required
          maxLength={60}
          autoFocus
          autoComplete="off"
          aria-label="Client name"
          className="min-w-0 flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-sm text-zinc-100 focus:border-zinc-500 focus:outline-none"
        />
        <button disabled={saving} className="rounded-full bg-zinc-50 px-3.5 py-1.5 text-sm font-medium text-zinc-950 disabled:opacity-50">
          {saving ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={() => setEditing(false)} className="px-1 text-sm text-zinc-400 hover:text-zinc-200">
          Cancel
        </button>
        {state.message && !state.ok ? (
          <p role="alert" className="w-full text-xs text-red-300">
            {state.message}
          </p>
        ) : null}
      </form>
    );
  return (
    <div className="ml-auto flex items-center gap-3 text-xs text-zinc-500">
      <button type="button" onClick={() => setEditing(true)} className="hover:text-zinc-200">
        Rename
      </button>
      <button type="button" onClick={remove} disabled={removing} className="hover:text-red-300 disabled:opacity-50">
        {removing ? "Removing…" : "Remove"}
      </button>
      {error ? (
        <span role="alert" className="text-red-300">
          {error}
        </span>
      ) : null}
    </div>
  );
}
