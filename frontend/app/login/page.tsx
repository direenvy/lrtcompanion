"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { supabase } from "@/lib/supabase";

export default function LoginPage() {
  const { sendEmailOtp, verifyEmailOtp, signInWithGoogle, user } = useAuth();
  const router = useRouter();

  const [email,      setEmail]      = useState("");
  const [code,       setCode]       = useState("");
  const [otpStep,    setOtpStep]    = useState<"email" | "code">("email");
  const [loading,    setLoading]    = useState(false);
  const [gLoading,   setGLoading]   = useState(false);
  const [error,      setError]      = useState("");
  const [success,    setSuccess]    = useState("");
  const [showEmail,  setShowEmail]  = useState(false);
  const [processing, setProcessing] = useState(false);

  // Handle implicit OAuth flow — Supabase returns #access_token in the hash.
  // The Supabase JS client processes it automatically; we just need to wait
  // for the session to appear then redirect.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!window.location.hash.includes("access_token")) return;

    setProcessing(true);
    // Give the Supabase client ~600 ms to parse the hash and fire onAuthStateChange
    const id = setTimeout(async () => {
      const { data: { session } } = await supabase.auth.getSession();
      if (session) router.replace("/settings");
      else setProcessing(false);
    }, 600);
    return () => clearTimeout(id);
  }, [router]);

  // Redirect once user is confirmed — must be in useEffect, not during render
  useEffect(() => {
    if (user) router.replace("/settings");
  }, [user, router]);

  if (processing || user) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "40vh", gap: 16 }}>
        <span className="anim-spin" style={{ width: 24, height: 24, border: "3px solid rgba(0,0,0,0.1)", borderTopColor: "#22c55e", borderRadius: "50%", display: "inline-block" }} />
        <p style={{ color: "#737373", fontSize: 13 }}>Signing you in with Google…</p>
      </div>
    );
  }

  const handleGoogle = async () => {
    setGLoading(true); setError("");
    const err = await signInWithGoogle();
    if (err) { setError(err); setGLoading(false); }
    // On success the browser navigates away — no need to setGLoading(false)
  };

  const handleSendCode = async () => {
    if (!email.trim()) return;
    setLoading(true); setError(""); setSuccess("");
    const err = await sendEmailOtp(email.trim());
    setLoading(false);
    if (err) {
      setError(err);
    } else {
      setOtpStep("code");
      setSuccess(`We emailed a 6-digit code to ${email.trim()}. It expires in a few minutes.`);
    }
  };

  const handleVerifyCode = async () => {
    if (code.trim().length < 6) return;
    setLoading(true); setError(""); setSuccess("");
    const err = await verifyEmailOtp(email.trim(), code);
    setLoading(false);
    if (err) setError(err);
    else router.push("/settings");
  };

  return (
    <div className="anim-fade-up" style={{ maxWidth: 400, margin: "0 auto" }}>

      <p className="section-label" style={{ marginBottom: 8 }}>LRT Companion</p>
      <h1 style={{ fontFamily: "var(--font-sans)", fontSize: 40, fontWeight: 400, letterSpacing: "-0.01em", color: "#000000", marginBottom: 12 }}>
        Sign In
      </h1>
      <p style={{ color: "#737373", fontSize: 13, lineHeight: 1.65, marginBottom: "2rem" }}>
        Save your route preferences, home &amp; work stations, and avoid lines across every session.
      </p>

      <div className="card" style={{ padding: "1.75rem", display: "flex", flexDirection: "column", gap: 12 }}>

        {/* Google Sign In — primary CTA */}
        <button
          onClick={handleGoogle}
          disabled={gLoading}
          style={{
            display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
            width: "100%", padding: "11px 16px",
            background: gLoading ? "rgba(0,0,0,0.04)" : "rgba(0,0,0,0.07)",
            border: "1px solid rgba(0,0,0,0.15)",
            borderRadius: 10, cursor: gLoading ? "not-allowed" : "pointer",
            fontSize: 13, fontWeight: 600, color: "#000000",
            transition: "all 0.15s",
          }}
        >
          {gLoading ? (
            <span className="anim-spin" style={{ width: 16, height: 16, border: "2px solid rgba(0,0,0,0.15)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block" }} />
          ) : (
            /* Google G logo SVG */
            <svg width="18" height="18" viewBox="0 0 48 48">
              <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
              <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
              <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
              <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.31-8.16 2.31-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
            </svg>
          )}
          {gLoading ? "Redirecting to Google…" : "Continue with Google"}
        </button>

        {/* Divider */}
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ flex: 1, height: 1, background: "rgba(0,0,0,0.06)" }} />
          <span style={{ fontSize: 11, color: "#8f8f8f" }}>or</span>
          <div style={{ flex: 1, height: 1, background: "rgba(0,0,0,0.06)" }} />
        </div>

        {/* Email/password toggle */}
        <button
          onClick={() => setShowEmail(p => !p)}
          style={{
            background: "none", border: "1px solid rgba(0,0,0,0.07)",
            borderRadius: 9, padding: "9px 14px", cursor: "pointer",
            fontSize: 12, color: "#737373", display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
          }}
        >
          <span>✉</span>
          {showEmail ? "Hide email sign-in" : "Sign in with an email code instead"}
        </button>

        {/* Email OTP flow — passwordless, two steps */}
        {showEmail && (
          <div className="anim-fade-in" style={{ display: "flex", flexDirection: "column", gap: 12 }}>

            {otpStep === "email" ? (
              <>
                <div>
                  <label style={{ fontSize: 10, color: "#737373", display: "block", marginBottom: 5, letterSpacing: "0.08em", textTransform: "uppercase" }}>Email</label>
                  <input className="input" type="email" placeholder="you@example.com"
                    value={email} onChange={e => setEmail(e.target.value)}
                    onKeyDown={e => e.key === "Enter" && handleSendCode()} />
                  <p style={{ fontSize: 11, color: "#8f8f8f", marginTop: 6 }}>
                    No password needed — we'll email you a 6-digit code.
                  </p>
                </div>
                <button
                  className="btn-primary" onClick={handleSendCode}
                  disabled={loading || !email.trim()}
                >
                  {loading
                    ? <><span className="anim-spin" style={{ width: 12, height: 12, border: "2px solid rgba(255,255,255,0.4)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block" }} /> Sending code…</>
                    : "Email me a code →"}
                </button>
              </>
            ) : (
              <>
                <div>
                  <label style={{ fontSize: 10, color: "#737373", display: "block", marginBottom: 5, letterSpacing: "0.08em", textTransform: "uppercase" }}>6-digit code</label>
                  <input className="input" type="text" inputMode="numeric" autoComplete="one-time-code"
                    placeholder="000000" maxLength={6}
                    style={{ fontSize: 22, letterSpacing: "0.4em", textAlign: "center" }}
                    value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ""))}
                    onKeyDown={e => e.key === "Enter" && handleVerifyCode()} />
                </div>
                <button
                  className="btn-primary" onClick={handleVerifyCode}
                  disabled={loading || code.trim().length < 6}
                >
                  {loading
                    ? <><span className="anim-spin" style={{ width: 12, height: 12, border: "2px solid rgba(255,255,255,0.4)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block" }} /> Verifying…</>
                    : "Verify & Sign In →"}
                </button>
                <button
                  onClick={() => { setOtpStep("email"); setCode(""); setSuccess(""); setError(""); }}
                  style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: "#737373", textDecoration: "underline" }}
                >
                  Different email / resend code
                </button>
              </>
            )}
          </div>
        )}

        {error && (
          <div className="anim-fade-in" style={{ padding: "10px 12px", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 8, fontSize: 12, color: "#ef4444" }}>
            {error}
          </div>
        )}
        {success && (
          <div className="anim-fade-in" style={{ padding: "10px 12px", background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.2)", borderRadius: 8, fontSize: 12, color: "#22c55e" }}>
            {success}
          </div>
        )}
      </div>

      <p style={{ fontSize: 11, color: "#8f8f8f", marginTop: 16, textAlign: "center" }}>
        Your preferences are stored securely in Supabase and never shared.
      </p>
    </div>
  );
}
