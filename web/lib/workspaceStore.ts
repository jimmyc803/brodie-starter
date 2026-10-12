import 'server-only';
import { supabaseServer } from '@/lib/supabase/server';
import type { CoachWorkspaceStore } from '@/lib/coachWorkspace';

export function workspaceStore(): CoachWorkspaceStore {
  const db = supabaseServer();
  return {
    async coach(token) {
      const { data, error } = await db.from('coaches').select('id,name').eq('share_token', token).maybeSingle();
      if (error) throw new Error('Coach lookup failed');
      return data;
    },
    async createCoach(coach) {
      const { error } = await db.from('coaches').insert(coach);
      if (error) throw new Error('Coach creation failed');
    },
    async createClient(client) {
      const { error } = await db.from('clients').insert(client);
      if (error) throw new Error('Client creation failed');
    },
    async removeCoach(id) {
      const { error } = await db.from('coaches').delete().eq('id', id);
      if (error) throw new Error('Workspace cleanup failed');
    },
  };
}
