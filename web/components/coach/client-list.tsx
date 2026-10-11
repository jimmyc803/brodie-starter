"use client";

import Link from "next/link";
import { useState } from "react";

import { AddClient } from "@/components/coach/add-client";
import type { ClientStatus, ClientSummary } from "@/lib/coach-status";

const GROUPS: { status: ClientStatus; label: string; dot: string }[] = [
  { status: "review", label: "Needs review", dot: "#ef4444" },
  { status: "on_track", label: "On track", dot: "#22c55e" },
  { status: "inactive", label: "Inactive", dot: "#52525b" },
];

// The coach's roster: search, a filter per status, and clients grouped so the ones that need the coach come first.
export function ClientList({
  clients,
  base,
  selectedId,
  addToken,
}: {
  clients: ClientSummary[];
  base: string;
  selectedId: string | null;
  addToken?: string; // the coach link, when this coach may add clients (never on the public demo)
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<ClientStatus | "all">("all");
  const q = query.trim().toLowerCase();
  const shown = clients.filter((c) => (filter === "all" || c.status === filter) && (!q || c.name.toLowerCase().includes(q)));
  const count = (s: ClientStatus) => clients.filter((c) => c.status === s).length;

  return (
    <nav aria-label="Clients" className="rounded-2xl border border-zinc-800 bg-zinc-900 p-3">
      {addToken ? (
        <div className="mb-2">
          <AddClient token={addToken} base={base} />
        </div>
      ) : null}
      {clients.length > 3 ? (
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search clients"
          aria-label="Search clients"
          className="w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:border-zinc-600 focus:outline-none"
        />
      ) : null}
      <div className="mt-2 flex flex-wrap gap-1 text-xs" role="group" aria-label="Filter clients">
        <Chip active={filter === "all"} onClick={() => setFilter("all")}>
          All {clients.length}
        </Chip>
        {GROUPS.map((g) =>
          count(g.status) ? (
            <Chip key={g.status} active={filter === g.status} onClick={() => setFilter(g.status)}>
              {g.label} {count(g.status)}
            </Chip>
          ) : null,
        )}
      </div>

      {shown.length === 0 ? <p className="px-2 py-6 text-center text-sm text-zinc-500">No clients match.</p> : null}
      {GROUPS.map((g) => {
        const list = shown.filter((c) => c.status === g.status);
        if (!list.length) return null;
        return (
          <div key={g.status} className="mt-4">
            <p className="px-2 text-xs text-zinc-500">{g.label}</p>
            <ul className="mt-1 space-y-0.5">
              {list.map((c) => {
                const active = c.id === selectedId;
                return (
                  <li key={c.id}>
                    <Link
                      href={`${base}?c=${encodeURIComponent(c.id)}`}
                      aria-current={active ? "page" : undefined}
                      className={`flex items-center gap-3 rounded-lg px-2 py-2 transition-colors ${
                        active ? "bg-zinc-800" : "hover:bg-zinc-800/50"
                      } ${c.status === "inactive" && !active ? "opacity-60" : ""}`}
                    >
                      <span className="grid size-8 shrink-0 place-items-center rounded-full bg-zinc-800 text-sm font-medium text-zinc-200">
                        {c.name.charAt(0).toUpperCase()}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-zinc-100">{c.name}</span>
                        <span className="block truncate text-xs text-zinc-400">{c.detail}</span>
                      </span>
                      <span className="size-2 shrink-0 rounded-full" style={{ background: g.dot }} aria-hidden />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full px-2.5 py-1 transition-colors ${active ? "bg-zinc-800 text-zinc-100" : "text-zinc-400 hover:text-zinc-200"}`}
    >
      {children}
    </button>
  );
}
