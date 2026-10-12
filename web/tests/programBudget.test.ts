import { beforeEach, describe, expect, it, vi } from 'vitest';
const { rpc } = vi.hoisted(() => ({ rpc: vi.fn() }));
vi.mock('@/lib/supabase/server', () => ({ supabaseServer: () => ({ rpc }) }));
import { consumeProgramBudget } from '@/lib/programBudget';

beforeEach(() => { rpc.mockReset(); });
describe('durable request budget adapter', () => {
  it('consumes the server-side budget and permits only a positive boolean reply', async () => {
    rpc.mockResolvedValue({ data: true, error: null });
    await expect(consumeProgramBudget('parser')).resolves.toBeUndefined();
    expect(rpc).toHaveBeenCalledWith('consume_program_budget', { p_action: 'parser' });
  });
  it('denies exhausted workspace and parser allowances with retry guidance', async () => {
    rpc.mockResolvedValue({ data: false, error: null });
    await expect(consumeProgramBudget('workspace')).rejects.toThrow('Workspace creation is at its hourly limit');
    await expect(consumeProgramBudget('parser')).rejects.toThrow('PDF reading is at its hourly limit');
  });
  it('fails closed when migration is missing without exposing raw database errors', async () => {
    rpc.mockResolvedValue({ data: null, error: { message: 'database-secret' } });
    await expect(consumeProgramBudget('parser')).rejects.toThrow('apply the program budgets migration');
    await expect(consumeProgramBudget('parser')).rejects.not.toThrow('database-secret');
  });
  it('rejects malformed successful-looking RPC replies', async () => {
    for (const data of [undefined, null, 1, 'true', [], { allowed: true }]) {
      rpc.mockResolvedValue({ data, error: null });
      await expect(consumeProgramBudget('workspace')).rejects.toThrow('could not be checked');
    }
  });
  it('turns thrown transport errors into a safe failure', async () => {
    rpc.mockImplementation(async () => { throw new Error('database-secret'); });
    await expect(consumeProgramBudget('parser')).rejects.toThrow('could not be checked');
  });
});
