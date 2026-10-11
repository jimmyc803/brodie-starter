import 'server-only';
import { supabaseServer } from '@/lib/supabase/server';
import type { ParsedProgram } from '@/lib/parseProgram';
import type { ProgramStore } from '@/lib/programWorkflow';

export function programStore(): ProgramStore<ParsedProgram> {
  const db = supabaseServer();
  return {
    async coach(token) {
      const { data, error } = await db.from('coaches').select('id,name').eq('share_token', token).maybeSingle();
      if (error) throw new Error('Coach lookup failed');
      return data;
    },
    async upload(path, bytes) {
      const { error } = await db.storage.from('programs').upload(path, bytes, { contentType: 'application/pdf', upsert: false });
      if (error) throw new Error('Upload failed');
    },
    async remove(path) {
      const { error } = await db.storage.from('programs').remove([path]);
      if (error) throw new Error('Cleanup failed');
    },
    async save(token, path, program) {
      const { error } = await db.rpc('save_coach_program', { p_token: token, p_pdf_path: path, p_program: program });
      if (error) throw new Error('Program save failed');
    },
    async assign(token, clientId, dayId) {
      const { error } = await db.rpc('assign_coach_program_day', { p_token: token, p_client_id: clientId, p_day_id: dayId });
      if (error) throw new Error('Assignment failed');
    },
  };
}
