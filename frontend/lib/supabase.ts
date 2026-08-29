import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

// supabase-js v2 serialises every auth-token access through the browser's
// Navigator LockManager. If any tab/HMR-stale client holds that lock, EVERY
// later call — getSession(), and even .from().upsert() (which fetches the
// token internally) — queues forever. Symptom: "Saving…" never resolves.
// Fix: run the callback directly instead of taking the shared browser lock.
// Trade-off: token refreshes are no longer cross-tab coordinated — harmless
// here (worst case is a redundant refresh request).
export const supabase = createClient(url, key, {
  auth: {
    lock: async (_name: string, _acquireTimeout: number, fn: () => Promise<any>) => fn(),
  },
});
