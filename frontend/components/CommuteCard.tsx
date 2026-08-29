"use client";
import { useState, useEffect } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { apiBase } from "@/lib/api";

function greeting() {
  const h = new Date().getHours();
  if (h < 5)  return "Working late?";
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export default function CommuteCard() {
  const { user, prefs } = useAuth();
  const [lineStatus, setLineStatus] = useState<any>(null);
  const [reversed, setReversed] = useState(false);

  useEffect(() => {
    if (!user) return;
    fetch(`${apiBase()}/api/dashboard/line-status`)
      .then(r => r.ok ? r.json() : null)
      .then(setLineStatus)
      .catch(() => setLineStatus(null));
  }, [user]);

  if (!user || !prefs.home_station || !prefs.work_station) return null;

  const from = reversed ? prefs.work_station : prefs.home_station;
  const to   = reversed ? prefs.home_station : prefs.work_station;

  // Check for any disrupted lines (we don't know exact path, but warn if anything is red)
  const disruptedLines: any[] = lineStatus?.lines
    ? Object.values(lineStatus.lines).filter((l: any) => l.status === "disrupted")
    : [];
  const hasDisruption = disruptedLines.length > 0;

  const planUrl = `/reroute?o=${encodeURIComponent(from)}&d=${encodeURIComponent(to)}&auto=1`;

  return (
    <div className="card anim-fade-up" style={{
      marginBottom: "2rem",
      padding: "1.5rem",
      borderColor: hasDisruption ? "rgba(239,68,68,0.25)" : "rgba(34,197,94,0.18)",
      background:  hasDisruption ? "rgba(239,68,68,0.04)" : "rgba(34,197,94,0.03)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
        <span style={{ fontSize: 11, color: "#737373" }}>
          {greeting()}, {user.email?.split("@")[0]}
        </span>
        <span style={{ marginLeft: "auto", fontSize: 10, color: "#8f8f8f" }}>YOUR COMMUTE</span>
      </div>

      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        fontFamily: "var(--font-sans)", fontWeight: 700,
        fontSize: "clamp(15px, 3vw, 18px)",
        color: "#000000", marginBottom: 14,
        flexWrap: "wrap",
      }}>
        <span>{from}</span>
        <span style={{ color: "#737373" }}>→</span>
        <span>{to}</span>
        <button
          onClick={() => setReversed(p => !p)}
          aria-label="Reverse direction"
          style={{
            marginLeft: "auto", background: "rgba(0,0,0,0.05)",
            border: "1px solid rgba(0,0,0,0.1)", borderRadius: 6,
            color: "#5f5f5f", padding: "4px 10px", fontSize: 12, cursor: "pointer",
          }}
        >↔ Reverse</button>
      </div>

      {/* Status line */}
      <div style={{ fontSize: 12, color: hasDisruption ? "#ef4444" : "#22c55e", marginBottom: 16 }}>
        {hasDisruption ? (
          <>
            ⚠️ {disruptedLines.length} line{disruptedLines.length > 1 ? "s" : ""} disrupted —{" "}
            {disruptedLines.map((l: any) => l.name).join(", ")}.
            We'll route around them.
          </>
        ) : lineStatus ? (
          <>✓ All rail lines normal — routing should be straightforward</>
        ) : (
          <>Checking live line status…</>
        )}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Link href={planUrl} className="btn-primary" style={{ fontSize: 13 }}>
          {hasDisruption ? "Plan around disruption →" : "Open route map →"}
        </Link>
        <Link href="/status" className="btn-ghost" style={{ fontSize: 13 }}>
          Line Status
        </Link>
      </div>
    </div>
  );
}
