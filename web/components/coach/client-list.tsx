"use client";

import Link from "next/link";
import { useState } from "react";

import { Surface } from "@/components/ui/apple";
import type { ClientStatus, ClientSummary } from "@/lib/coach-status";

const GROUPS: { status: ClientStatus; label: string; dot: string }[] = [
  { status: "review", label: "Needs review", dot: "bg-critical" },
  { status: "on_track", label: "On track", dot: "bg-positive" },
  { status: "inactive", label: "Inactive", dot: "bg-ink-3" },
];

// The coach's roster: search, a filter per status, and clients grouped so the ones that need the coach come first.
export function ClientList({ clients, base, selectedId }: { clients: ClientSummary[]; base: string; selectedId: string | null }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<ClientStatus | "all">("all");
  const q = query.trim().toLowerCase();
  const shown = clients.filter((c) => (filter === "all" || c.status === filter) && (!q || c.name.toLowerCase().includes(q)));
  const count = (s: ClientStatus) => clients.filter((c) => c.status === s).length;

  return (
    <nav aria-label="Clients">
      {clients.length > 3 ? (
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search clients"
          aria-label="Search clients"
          className="t-callout w-full rounded-full bg-fill px-4 py-2 text-ink placeholder:text-ink-3 focus:outline-2 focus:outline-accent"
        />
      ) : null}
      <div className="mt-3 flex flex-wrap gap-1 t-footnote" role="group" aria-label="Filter clients">
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

      {shown.length === 0 ? <p className="px-2 py-6 text-center t-callout text-ink-2">No clients match.</p> : null}
      {GROUPS.map((g) => {
        const list = shown.filter((c) => c.status === g.status);
        if (!list.length) return null;
        return (
          <div key={g.status} className="mt-5">
            <p className="mb-1.5 px-4 t-footnote text-ink-2">{g.label}</p>
            <Surface className="overflow-hidden">
            <ul className="divide-y divide-hairline">
              {list.map((c) => {
                const active = c.id === selectedId;
                return (
                  <li key={c.id}>
                    <Link
                      href={`${base}?c=${encodeURIComponent(c.id)}`}
                      aria-current={active ? "page" : undefined}
                      className={`flex items-center gap-3 px-4 py-3 transition-colors ${
                        active ? "bg-fill" : "hover:bg-fill"
                      }`}
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate t-headline text-ink">{c.name}</span>
                        <span className="block truncate t-footnote text-ink-2">{c.detail}</span>
                      </span>
                      <span className={`size-2 shrink-0 rounded-full ${g.dot}`} aria-hidden />
                    </Link>
                  </li>
                );
              })}
            </ul>
            </Surface>
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
      className={`rounded-full px-3 py-1 transition-colors ${active ? "bg-accent-fill text-white" : "bg-fill text-ink-2 hover:text-ink"}`}
    >
      {children}
    </button>
  );
}
