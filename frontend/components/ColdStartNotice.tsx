"use client";
import { useEffect, useState } from "react";
import { COLD_START_EVENT } from "@/lib/api";

/* Tells the user the server is waking up.
   The backend runs on a tier that sleeps after ~15 minutes idle, so the first
   request of a visit can take over a minute. Without this the app looks hung,
   and in front of an audience it looks broken. The honest version of that
   trade-off is to say what is happening and roughly how long it takes.
   Nothing renders unless a request has actually been slow for a few seconds,
   so a warm instance never shows this. */
export default function ColdStartNotice() {
  const [slow, setSlow] = useState(false);
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const onSlow = (e: Event) => {
      const next = (e as CustomEvent<{ slow: boolean }>).detail?.slow ?? false;
      setSlow(next);
      if (!next) setSeconds(0);
    };
    window.addEventListener(COLD_START_EVENT, onSlow);
    return () => window.removeEventListener(COLD_START_EVENT, onSlow);
  }, []);

  useEffect(() => {
    if (!slow) return;
    const t = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [slow]);

  if (!slow) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "fixed", left: 16, right: 16, bottom: 16, zIndex: 9999,
        maxWidth: 420, margin: "0 auto",
        background: "#ffffff", color: "#2e2e2e",
        border: "1px solid rgba(0,0,0,0.10)", borderRadius: 12,
        boxShadow: "0 6px 24px rgba(0,0,0,0.10)",
        padding: "11px 14px", fontSize: 12.5, lineHeight: 1.55,
      }}
    >
      <strong style={{ fontWeight: 600 }}>Waking the server…</strong>{" "}
      It sleeps when idle, so the first request can take up to a minute.
      {seconds > 8 && (
        <span style={{ color: "#737373" }}> ({seconds}s)</span>
      )}
    </div>
  );
}
