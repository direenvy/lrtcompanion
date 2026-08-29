"use client";
import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { supabase } from "@/lib/supabase";
import type { User } from "@supabase/supabase-js";
import type { RoutePreferences } from "@/lib/api";

export interface UserPreferences extends RoutePreferences {
  home_station: string;
  work_station: string;
}

export const DEFAULT_USER_PREFS: UserPreferences = {
  priority:            "fastest",
  prefer_shelter:      false,
  avoid_lines:         [],
  require_wheelchair:  false,
  prefer_less_walking: false,
  require_tactile:     false,
  prefer_quiet:        false,
  max_walk_minutes:    0,
  prefer_safer_walk:   false,
  home_station:        "",
  work_station:        "",
};

interface AuthCtx {
  user:              User | null;
  prefs:             UserPreferences;
  loading:           boolean;
  signInWithGoogle:  () => Promise<string | null>;
  signIn:            (email: string, pass: string) => Promise<string | null>;
  signUp:            (email: string, pass: string) => Promise<string | null>;
  sendEmailOtp:      (email: string) => Promise<string | null>;
  verifyEmailOtp:    (email: string, code: string) => Promise<string | null>;
  signOut:           () => Promise<void>;
  savePreferences:   (p: UserPreferences) => Promise<string | null>;
}

const AuthContext = createContext<AuthCtx>({
  user: null, prefs: DEFAULT_USER_PREFS, loading: true,
  signInWithGoogle: async () => null,
  signIn: async () => null, signUp: async () => null,
  sendEmailOtp: async () => null, verifyEmailOtp: async () => null,
  signOut: async () => {}, savePreferences: async () => null,
});

export const useAuth = () => useContext(AuthContext);

async function fetchPrefs(uid: string): Promise<UserPreferences | null> {
  const { data } = await supabase
    .from("user_preferences")
    .select("*")
    .eq("user_id", uid)
    .single();
  if (!data) return null;
  return {
    priority:            data.priority            ?? "fastest",
    prefer_shelter:      data.prefer_shelter      ?? false,
    // dedupe: a historical race could persist a duplicate line id in the DB
    avoid_lines:         [...new Set<string>(data.avoid_lines ?? [])],
    require_wheelchair:  data.require_wheelchair  ?? false,
    prefer_less_walking: data.prefer_less_walking ?? false,
    require_tactile:     data.require_tactile     ?? false,
    prefer_quiet:        data.prefer_quiet        ?? false,
    max_walk_minutes:    data.max_walk_minutes    ?? 0,
    prefer_safer_walk:   data.prefer_safer_walk   ?? false,
    home_station:        data.home_station        ?? "",
    work_station:        data.work_station        ?? "",
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user,    setUser]    = useState<User | null>(null);
  const [prefs,   setPrefs]   = useState<UserPreferences>(DEFAULT_USER_PREFS);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      setUser(session?.user ?? null);
      if (session?.user) {
        const p = await fetchPrefs(session.user.id);
        if (p) setPrefs(p);
      }
      setLoading(false);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange(async (_evt, session) => {
      setUser(session?.user ?? null);
      if (session?.user) {
        const p = await fetchPrefs(session.user.id);
        if (p) setPrefs(p);
      } else {
        setPrefs(DEFAULT_USER_PREFS);
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  const signInWithGoogle = async () => {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${typeof window !== "undefined" ? window.location.origin : ""}/auth/callback`,
      },
    });
    return error?.message ?? null;
  };

  const signIn = async (email: string, pass: string) => {
    const { error } = await supabase.auth.signInWithPassword({ email, password: pass });
    return error?.message ?? null;
  };

  const signUp = async (email: string, pass: string) => {
    const { error } = await supabase.auth.signUp({ email, password: pass });
    return error?.message ?? null;
  };

  // Passwordless: email a 6-digit one-time code (creates the account if new).
  const sendEmailOtp = async (email: string) => {
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { shouldCreateUser: true },
    });
    return error?.message ?? null;
  };

  const verifyEmailOtp = async (email: string, code: string) => {
    const { error } = await supabase.auth.verifyOtp({
      email,
      token: code.trim(),
      type: "email",
    });
    return error?.message ?? null;
  };

  const signOut = async () => {
    // supabase.auth.signOut() can hang on the same internal lock that broke
    // getSession() in savePreferences — race it with a timeout and always
    // clear local state, then hard-reload so every component resets.
    try {
      await Promise.race([
        supabase.auth.signOut({ scope: "local" }),
        new Promise((resolve) => setTimeout(resolve, 2000)),
      ]);
    } finally {
      setUser(null);
      setPrefs(DEFAULT_USER_PREFS);
      window.location.href = "/";
    }
  };

  const savePreferences = async (p: UserPreferences) => {
    if (!user) return "Not logged in";

    // The upsert acquires the same internal auth lock that has hung
    // getSession()/signOut() before (see lib/supabase.ts) — so besides the
    // lock bypass there, race it with a timeout: the Save button must NEVER
    // hang forever, whatever supabase-js is doing internally.
    const upsert = supabase.from("user_preferences").upsert(
      {
        user_id:             user.id,
        priority:            p.priority,
        prefer_shelter:      p.prefer_shelter,
        avoid_lines:         [...new Set(p.avoid_lines)],   // never persist duplicates
        require_wheelchair:  p.require_wheelchair,
        prefer_less_walking: p.prefer_less_walking,
        require_tactile:     p.require_tactile,
        prefer_quiet:        p.prefer_quiet,
        max_walk_minutes:    p.max_walk_minutes,
        prefer_safer_walk:   p.prefer_safer_walk,
        home_station:        p.home_station,
        work_station:        p.work_station,
        updated_at:          new Date().toISOString(),
      },
      { onConflict: "user_id" }
    );
    const result = await Promise.race([
      upsert,
      new Promise<{ error: { message: string }; status: number }>((resolve) =>
        setTimeout(() => resolve({
          error: { message: "Save timed out — please refresh the page and try again" },
          status: 0,
        }), 8000)
      ),
    ]);

    const { error, status } = result as { error: { message: string } | null; status: number };
    if (error) {
      console.error("[savePreferences] error:", error.message, "status:", status);
      return `${error.message}${status ? ` (${status})` : ""}`;
    }
    setPrefs(p);
    return null;
  };

  return (
    <AuthContext.Provider value={{ user, prefs, loading, signInWithGoogle, signIn, signUp, sendEmailOtp, verifyEmailOtp, signOut, savePreferences }}>
      {children}
    </AuthContext.Provider>
  );
}
