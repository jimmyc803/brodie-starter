import 'server-only';
import { supabaseServer } from '@/lib/supabase/server';
import { WorkflowError } from '@/lib/programWorkflow';
const unavailable = 'Program safety limits are not configured or could not be checked. Ask your administrator to apply the program budgets migration and verify database access, then retry.';

/** Shared database budget: serverless instances cannot each mint their own allowance. */
export async function consumeProgramBudget(action: 'workspace' | 'parser'): Promise<void> {
  try {
    const { data, error } = await supabaseServer().rpc('consume_program_budget', { p_action: action });
    if (error || typeof data !== 'boolean') throw new WorkflowError(unavailable);
    if (!data) {
      throw new WorkflowError(action === 'workspace'
        ? 'Workspace creation is at its hourly limit. Please try again in an hour.'
        : 'PDF reading is at its hourly limit. Please try again in an hour. No program was saved.');
    }
  } catch (error) {
    if (error instanceof WorkflowError) throw error;
    throw new WorkflowError(unavailable);
  }
}
