import type { CoachStatus } from "@/lib/coach-view";
import { readOnlyCoachToken } from "@/lib/programWorkflow";

// Who may add real clients and hand out workout links: an approved coach on their own private link.
// The public demo link is view-only; pending coaches (applied on /start) explore the sandbox until the team approves them.
export function canManageClients(token: string, status: CoachStatus): boolean {
  return token !== "demo" && !readOnlyCoachToken(token) && status === "approved";
}
