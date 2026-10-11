type Client = { id: string; name: string };
type DayLabel = { id: string; label: string };

/** Resolve only against the coach-owned clients and day labels fetched by the page. */
export function currentAssignments(clients: Client[], days: DayLabel[], assignments: unknown[]) {
  const clientIds = new Set(clients.map(client => client.id));
  const labels = new Map(days.map(day => [day.id, day.label]));
  const latest = new Map<string, { dayId: string; time: number }>();
  for (const row of assignments) {
    if (!row || typeof row !== 'object') continue;
    const value = row as Record<string, unknown>;
    if (value.active !== true || typeof value.client_id !== 'string' || !clientIds.has(value.client_id)
      || typeof value.program_day_id !== 'string' || typeof value.assigned_at !== 'string') continue;
    const time = Date.parse(value.assigned_at);
    if (!Number.isFinite(time)) continue;
    const previous = latest.get(value.client_id);
    if (!previous || time > previous.time) latest.set(value.client_id, { dayId: value.program_day_id, time });
  }
  return clients.map(client => {
    const selected = latest.get(client.id);
    return { ...client, assignment: selected ? labels.get(selected.dayId) ?? 'Assigned day unavailable' : 'No active assignment' };
  });
}
