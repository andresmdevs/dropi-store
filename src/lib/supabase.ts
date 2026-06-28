import { createClient, type SupabaseClient } from '@supabase/supabase-js';

const url = import.meta.env.PUBLIC_SUPABASE_URL;
const anonKey = import.meta.env.PUBLIC_SUPABASE_ANON_KEY;

/**
 * Cliente de Supabase. Es `null` mientras no configures las variables, para que
 * el sitio arranque y despliegue sin Supabase todavía. Cuando agregues las env
 * vars, el cliente queda disponible automáticamente.
 */
export const supabase: SupabaseClient | null =
  url && anonKey ? createClient(url, anonKey) : null;
