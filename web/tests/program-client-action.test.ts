import { beforeEach, expect, it, vi } from 'vitest';
import { addClientAction } from '@/app/c/[token]/program/client-actions';

const db = vi.hoisted(() => ({ from: vi.fn(), insert: vi.fn(), revalidate: vi.fn(), status: 'pending', count: 0 }));
vi.mock('@/lib/supabase/server', () => ({ supabaseServer: () => ({ from: db.from }) }));
vi.mock('next/cache', () => ({ revalidatePath: db.revalidate }));
const token = 'private-coach-valid-token-0001';
const form = () => { const data = new FormData(); data.set('client_name', 'Ryan'); return data; };

beforeEach(() => {
  vi.clearAllMocks();
  db.status = 'pending'; db.count = 0;
  db.insert.mockReturnValue({ select: () => ({ single: async () => ({ data: { id: 'new-client' }, error: null }) }) });
  db.from.mockImplementation((table: string) => table === 'coaches'
    ? { select: () => ({ eq: () => ({ maybeSingle: async () => ({ data: { id: 'owned-coach', status: db.status }, error: null }) }) }) }
    : { select: () => ({ eq: async () => ({ count: db.count }) }), insert: db.insert });
});

it.each(['pending', 'rejected'])('Programs cannot create clients for a %s coach', async status => {
  db.status = status;
  const result = await addClientAction(token, { ok: false, message: '' }, form());
  expect(result.ok).toBe(false);
  expect(result.message).toContain('approved');
  expect(db.insert).not.toHaveBeenCalled();
});

it('Programs preserves the shared client cap', async () => {
  db.status = 'approved'; db.count = 200;
  expect((await addClientAction(token, { ok: false, message: '' }, form())).ok).toBe(false);
  expect(db.insert).not.toHaveBeenCalled();
});

it('approved coaches add an owned client and refresh both client and program views', async () => {
  db.status = 'approved';
  expect((await addClientAction(token, { ok: false, message: '' }, form())).ok).toBe(true);
  expect(db.insert).toHaveBeenCalledWith({ coach_id: 'owned-coach', name: 'Ryan' });
  expect(db.revalidate).toHaveBeenCalledWith(`/c/${token}/clients`);
  expect(db.revalidate).toHaveBeenCalledWith(`/c/${token}/program`);
});
