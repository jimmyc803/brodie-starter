import "server-only";

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

// Server code only. RLS is on with no policies (db/schema.sql), so every read goes through
// the service role key here, after the caller's token has been looked up. Never use the anon
// key in the browser, and never prefix these variables with NEXT_PUBLIC_.
let client: SupabaseClient | null = null;

export function supabaseServer(): SupabaseClient {
  if (client) return client;
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) {
    throw new Error(
      "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY. Set them in web/.env.local (local) or in Vercel env vars.",
    );
  }
  client = createClient(url, key, { auth: { persistSession: false } });
  return client;
}
