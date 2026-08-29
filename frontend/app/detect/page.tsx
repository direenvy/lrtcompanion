"use client";
import { useState } from "react";
import { detectDisruption, friendlyError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import LiveRegion from "@/components/LiveRegion";
import VoiceInput from "@/components/VoiceInput";

const EXAMPLES = [
  "Kelana Jaya line breakdown at KLCC, stuck 40 mins!",
  "MRT Kajang delayed again this morning, terrible!",
  "Service running smooth today, no complaints.",
];

const SENTIMENT_CFG: Record<string, { color: string; bg: string; bd: string }> = {
  negative: { color: "#ef4444", bg: "rgba(239,68,68,0.1)",  bd: "rgba(239,68,68,0.25)" },
  neutral:  { color: "#f59e0b", bg: "rgba(245,158,11,0.1)", bd: "rgba(245,158,11,0.25)" },
  positive: { color: "#22c55e", bg: "rgba(34,197,94,0.1)",  bd: "rgba(34,197,94,0.25)" },
};

const SENT_COLOR: Record<string, string> = {
  negative: "#ef4444",
  neutral:  "#f59e0b",
  positive: "#22c55e",
};

const ISSUE_COLOR: Record<string, string> = {
  breakdown:   "#ef4444",
  delay:       "#f97316",
  crowding:    "#eab308",
  other:       "#737373",
  information: "#3b82f6",
};

export default function DetectPage() {
  const { prefs } = useAuth();
  const [text, setText]       = useState("");
  const [result, setResult]   = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");

  const run = async () => {
    if (!text.trim()) return;
    setLoading(true); setError(""); setResult(null);
    try   { setResult(await detectDisruption(text)); }
    catch (e) { setError(friendlyError(e)); }
    finally { setLoading(false); }
  };

  const sc = result ? (SENTIMENT_CFG[result.sentiment] ?? SENTIMENT_CFG.neutral) : null;

  // Real sentiment bars from model probabilities
  const sentBars = result?.sentiment_scores
    ? Object.entries(result.sentiment_scores as Record<string, number>)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([label, pct]) => ({ label, pct, color: SENT_COLOR[label] ?? "#737373" }))
    : [];

  // Real issue bars sorted descending by confidence
  const issueBars = result?.issue_scores
    ? Object.entries(result.issue_scores as Record<string, number>)
        .sort(([, a], [, b]) => (b as number) - (a as number))
        .map(([label, pct]) => ({ label, pct: pct as number, color: ISSUE_COLOR[label] ?? "#737373" }))
    : [];

  // Classification result is the whole point of the page — announce it.
  const announcement = loading
    ? "Analysing your report, please wait."
    : result
      ? `Classified as ${result.sentiment} sentiment, issue type ${result.issue_type}.` +
        (result.disruption_alert
          ? " A disruption alert was raised and the status board updated."
          : " No disruption alert was raised.")
      : "";

  return (
    <div className="anim-fade-up" style={{ maxWidth: 960 }}>
      <LiveRegion message={announcement} />
      <LiveRegion message={error} politeness="assertive" />

      <p className="section-label" style={{ marginBottom: 8 }}>NLP Agent · TF-IDF + Logistic Regression</p>
      <h1 style={{ fontFamily: "var(--font-sans)", fontSize: 40, fontWeight: 400, letterSpacing: "-0.01em", color: "#000000", marginBottom: 12 }}>
        Self Reported Disruption
      </h1>
      <p style={{ color: "#737373", fontSize: 13.5, lineHeight: 1.65, marginBottom: "2rem" }}>
        This is an additional user submitted report to supplement disruption that is currently automatically detected by the ML system from social media posts.
      </p>

      {/* Input card */}
      <div className="card" style={{ padding: "1.5rem", marginBottom: 12 }}>
        {/* Describing a disruption by voice beats typing it on a phone
            platform, which is exactly where a commuter files one. The
            transcript lands IN the box rather than submitting, so a
            mis-heard station can be corrected before analysis. */}
        <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <label style={{ fontSize: 11, color: "#737373" }}>
            Post or complaint text
          </label>
          <VoiceInput
            onResult={t => setText(prev => (prev ? prev + " " : "") + t)}
            title="Describe the disruption by voice"
          />
        </div>
        <textarea
          className="textarea"
          style={{ height: 128 }}
          placeholder='"Kelana Jaya line broken down again at KLCC, been waiting 40 mins!"'
          value={text}
          onChange={(e) => setText(e.target.value)}
        />

        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "10px 0 14px" }}>
          {EXAMPLES.map((ex) => (
            <button key={ex} onClick={() => setText(ex)} className="pill-btn">
              {ex.slice(0, 42)}…
            </button>
          ))}
        </div>

        <button className="btn-primary" onClick={run} disabled={loading || !text.trim()}>
          {loading
            ? <><span className="anim-spin" style={{ width: 13, height: 13, border: "2px solid rgba(255,255,255,0.4)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block" }} /> Analysing…</>
            : "Analyse →"}
        </button>

        {error && (
          <div className="anim-fade-in" style={{ marginTop: 14, background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", color: "#ef4444", fontSize: 12, padding: "10px 14px", borderRadius: 10 }}>{error}</div>
        )}
      </div>

      {/* Loading skeleton */}
      {loading && (
        <div className="card anim-fade-in" style={{ padding: "1.5rem" }}>
          <div style={{ height: 11, width: 110, background: "rgba(0,0,0,0.06)", borderRadius: 5, marginBottom: 16 }} />
          <div style={{ display: "flex", gap: 8, marginBottom: 22 }}>
            <div style={{ height: 24, width: 110, background: "rgba(0,0,0,0.06)", borderRadius: 99 }} />
            <div style={{ height: 24, width: 90,  background: "rgba(0,0,0,0.06)", borderRadius: 99 }} />
            <div style={{ height: 24, width: 130, background: "rgba(0,0,0,0.06)", borderRadius: 99 }} />
          </div>
          <div style={{ height: 9, width: "85%", background: "rgba(0,0,0,0.05)", borderRadius: 5, marginBottom: 8 }} />
          <div style={{ height: 9, width: "65%", background: "rgba(0,0,0,0.05)", borderRadius: 5 }} />
        </div>
      )}

      {/* Result */}
      {result && sc && (
        <div className="card anim-fade-up" style={{ padding: "1.5rem" }}>
          <p className="section-label" style={{ marginBottom: 14 }}>Analysis Result</p>

          {/* Badges */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 24 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: sc.color, background: sc.bg, border: `1px solid ${sc.bd}`, padding: "4px 12px", borderRadius: 99 }}>
              Sentiment: {result.sentiment}
            </span>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#3b82f6", background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.25)", padding: "4px 12px", borderRadius: 99 }}>
              Issue: {result.issue_type}
            </span>
            {result.disruption_alert
              ? <span className="pulse-red" style={{ fontSize: 12, fontWeight: 700, color: "#fff", background: "#ef4444", padding: "4px 12px", borderRadius: 99 }}>🚨 Disruption Alert</span>
              : <span style={{ fontSize: 12, color: "#737373", background: "rgba(0,0,0,0.04)", border: "1px solid rgba(0,0,0,0.07)", padding: "4px 12px", borderRadius: 99 }}>✅ No Alert</span>
            }
            {result.method === "gemini_fallback" && (
              <span style={{ fontSize: 11, color: "#a855f7", background: "rgba(168,85,247,0.1)", border: "1px solid rgba(168,85,247,0.25)", padding: "4px 12px", borderRadius: 99 }}>
                ✦ Gemini fallback
              </span>
            )}
          </div>

          {/* Sentiment confidence bars — real model probabilities */}
          <p style={{ fontSize: 10, color: "#737373", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10 }}>Sentiment Confidence</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 22 }}>
            {sentBars.map((bar) => (
              <div key={bar.label} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ width: 58, textAlign: "right", fontSize: 11, color: "#737373", flexShrink: 0, textTransform: "capitalize" }}>{bar.label}</span>
                <div style={{ flex: 1, height: 5, background: "rgba(0,0,0,0.06)", borderRadius: 99, overflow: "hidden" }}>
                  <div className="bar-grow" style={{ height: "100%", width: `${bar.pct}%`, background: bar.color, borderRadius: 99 }} />
                </div>
                <span style={{ width: 36, fontSize: 10, color: "#8f8f8f", textAlign: "right" }}>{bar.pct}%</span>
              </div>
            ))}
          </div>

          {/* Issue type confidence bars — real model probabilities */}
          <p style={{ fontSize: 10, color: "#737373", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10 }}>Issue Type Confidence</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {issueBars.map((bar) => (
              <div key={bar.label} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ width: 72, textAlign: "right", fontSize: 11, color: "#737373", flexShrink: 0, textTransform: "capitalize" }}>{bar.label}</span>
                <div style={{ flex: 1, height: 5, background: "rgba(0,0,0,0.06)", borderRadius: 99, overflow: "hidden" }}>
                  <div className="bar-grow" style={{ height: "100%", width: `${bar.pct}%`, background: bar.color, borderRadius: 99 }} />
                </div>
                <span style={{ width: 36, fontSize: 10, color: "#8f8f8f", textAlign: "right" }}>{bar.pct}%</span>
              </div>
            ))}
          </div>

          {/* Next-step CTAs — pre-fill stations from Home/Work if available */}
          {result.disruption_alert && (() => {
            const o = prefs.home_station ?? "";
            const d = prefs.work_station ?? "";
            const planUrl = o && d
              ? `/reroute?o=${encodeURIComponent(o)}&d=${encodeURIComponent(d)}&auto=1`
              : "/reroute";
            return (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 22, paddingTop: 18, borderTop: "1px solid rgba(0,0,0,0.06)" }}>
                <a href={planUrl} className="btn-primary" style={{ fontSize: 12 }}>
                  {o && d ? `Plan ${o} → ${d} →` : "Plan a route →"}
                </a>
                <a href="/status"  className="btn-ghost"   style={{ fontSize: 12 }}>Check Line Status</a>
              </div>
            );
          })()}
        </div>
      )}

      {/* Meta */}
      <div className="card" style={{ marginTop: 12, padding: "0.7rem 1.1rem", display: "flex", flexWrap: "wrap", gap: "1rem" }}>
        {[["Model","TF-IDF + LR + SMOTE"],["Sentiment Acc","85.3%"],["Issue Acc","62.7%"],["macro-F1","0.65"],["Train set","573 posts"]].map(([k,v]) => (
          <span key={k} style={{ fontSize: 10 }}>
            <span style={{ color: "#8f8f8f" }}>{k}: </span>
            <span style={{ color: "#737373" }}>{v}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
