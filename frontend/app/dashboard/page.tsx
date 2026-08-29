"use client";
import { useState, useEffect } from "react";
import Link from "next/link";
import { getDashboardStats, friendlyError, apiBase } from "@/lib/api";

const SENT_COLOR: Record<string, string> = {
  negative: "#ef4444",
  neutral:  "#f59e0b",
  positive: "#22c55e",
};

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1)  return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function DashboardPage() {
  const [data, setData]       = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const load = async () => {
    setLoading(true); setError("");
    try {
      const d = await getDashboardStats();
      if (d.error) throw new Error(d.error);
      setData(d);
      setLastRefresh(new Date());
    } catch (e: any) {
      setError(friendlyError(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const dis  = data?.disruptions;
  const chat = data?.chats;
  const fb   = data?.feedback;
  const totalFb = (fb?.thumbs_up ?? 0) + (fb?.thumbs_down ?? 0);
  const satisfactionPct = totalFb > 0 ? Math.round((fb.thumbs_up / totalFb) * 100) : null;

  const statCards = data ? [
    { label: "Total Scans",   value: dis.total_scans,  sub: "disruption detections",  color: "#3b82f6" },
    { label: "Alerts Fired",  value: dis.total_alerts, sub: `${dis.total_scans > 0 ? Math.round(dis.total_alerts/dis.total_scans*100) : 0}% alert rate`, color: "#ef4444" },
    { label: "Chat Queries",  value: chat.total,        sub: "questions answered",      color: "#22c55e" },
    { label: "Satisfaction",  value: satisfactionPct != null ? `${satisfactionPct}%` : "—", sub: `${fb.thumbs_up} 👍  ${fb.thumbs_down} 👎`, color: "#f59e0b" },
  ] : [];

  return (
    <div className="anim-fade-up" style={{ maxWidth: 960 }}>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: "2rem" }}>
        <div>
          <p className="section-label" style={{ marginBottom: 8 }}>Live Analytics · Supabase</p>
          <h1 style={{ fontFamily: "var(--font-sans)", fontSize: 40, fontWeight: 400, letterSpacing: "-0.01em", color: "#000000", marginBottom: 12 }}>
            Knowledge Discovery & Data Analytics Dashboard
          </h1>
          <p style={{ color: "#737373", fontSize: 13.5 }}>
            Real-time logs from all three agents — detections, queries, and user feedback.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 4, flexShrink: 0 }}>
          {/* The multi-agent pipeline is a demonstration of the NLP -> Rerouting
              -> RAG chain rather than a commuter task, so it is reached from
              here instead of the main nav. */}
          <Link href="/orchestrate" className="btn-ghost" style={{ fontSize: 12, padding: "6px 14px", textDecoration: "none" }}>
            ⚙ Agent Pipeline
          </Link>
          <button
            className="btn-ghost"
            onClick={load}
            disabled={loading}
            style={{ fontSize: 12, padding: "6px 14px" }}
          >
            {loading ? "Loading…" : "↻ Refresh"}
          </button>
        </div>
      </div>

      {error && (
        <div style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", color: "#ef4444", fontSize: 12, padding: "10px 14px", borderRadius: 10, marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* Stat cards */}
      {loading && !data ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 24 }}>
          {[0,1,2,3].map(i => (
            <div key={i} className="card" style={{ padding: "1.1rem 1.2rem", opacity: 0.4 }}>
              <div style={{ height: 28, background: "rgba(0,0,0,0.06)", borderRadius: 6, marginBottom: 8 }} />
              <div style={{ height: 14, width: "60%", background: "rgba(0,0,0,0.04)", borderRadius: 4 }} />
            </div>
          ))}
        </div>
      ) : data && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 24 }}>
          {statCards.map(s => (
            <div key={s.label} className="card anim-fade-up" style={{ padding: "1.1rem 1.2rem" }}>
              <div style={{ fontFamily: "var(--font-sans)", fontSize: 32, fontWeight: 400, color: s.color, marginBottom: 2 }}>
                {s.value}
              </div>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#5f5f5f" }}>{s.label}</div>
              <div style={{ fontSize: 10, color: "#8f8f8f", marginTop: 3 }}>{s.sub}</div>
            </div>
          ))}
        </div>
      )}

      <GovDataCard />
      <LiveIngestionCard />

      {data && (
        <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 12 }}>

          {/* Left col: recent detections + sentiment breakdown */}
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

            {/* Sentiment breakdown */}
            <div className="card" style={{ padding: "1.25rem" }}>
              <p className="section-label" style={{ marginBottom: 14 }}>Sentiment Breakdown</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {Object.entries(dis.sentiment_counts as Record<string, number>).map(([label, count]) => {
                  const pct = dis.total_scans > 0 ? Math.round((count / dis.total_scans) * 100) : 0;
                  return (
                    <div key={label} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ width: 58, fontSize: 11, color: "#737373", textAlign: "right", textTransform: "capitalize", flexShrink: 0 }}>{label}</span>
                      <div style={{ flex: 1, height: 6, background: "rgba(0,0,0,0.05)", borderRadius: 99, overflow: "hidden" }}>
                        <div className="bar-grow" style={{ height: "100%", width: `${pct}%`, background: SENT_COLOR[label] ?? "#737373", borderRadius: 99 }} />
                      </div>
                      <span style={{ width: 42, fontSize: 10, color: "#8f8f8f", textAlign: "right" }}>{count} ({pct}%)</span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Recent detections */}
            <div className="card" style={{ padding: "1.25rem" }}>
              <p className="section-label" style={{ marginBottom: 14 }}>Recent Detections</p>
              {dis.recent.length === 0 ? (
                <p style={{ fontSize: 12, color: "#8f8f8f" }}>No detections yet — try the Detection page.</p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                  {dis.recent.map((row: any) => (
                    <div key={row.id} style={{
                      padding: "9px 0",
                      borderBottom: "1px solid rgba(0,0,0,0.04)",
                      display: "flex", flexDirection: "column", gap: 4,
                    }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
                        <span style={{
                          fontSize: 9, fontWeight: 700, textTransform: "capitalize",
                          color: SENT_COLOR[row.sentiment] ?? "#737373",
                          background: `${SENT_COLOR[row.sentiment] ?? "#737373"}18`,
                          border: `1px solid ${SENT_COLOR[row.sentiment] ?? "#737373"}30`,
                          padding: "1px 7px", borderRadius: 99,
                        }}>{row.sentiment}</span>
                        <span style={{ fontSize: 9, color: "#737373", background: "rgba(0,0,0,0.04)", border: "1px solid rgba(0,0,0,0.07)", padding: "1px 7px", borderRadius: 99 }}>
                          {row.issue_type}
                        </span>
                        {row.disruption_alert && (
                          <span style={{ fontSize: 9, fontWeight: 700, color: "#fff", background: "#ef4444", padding: "1px 7px", borderRadius: 99 }}>🚨 Alert</span>
                        )}
                        <span style={{
                          fontSize: 9, fontWeight: 600, padding: "1px 7px", borderRadius: 99,
                          color:      row.source === "x_official" ? "#0369a1" : "#5f5f5f",
                          border:     `1px solid ${row.source === "x_official" ? "#7dd3fc" : "#cdcdcd"}`,
                          background: row.source === "x_official" ? "#f0f9ff" : "#ffffff",
                        }}>
                          {row.source === "x_official" ? "✓ Official RapidKL"
                            : row.source === "x_live" ? "X live" : "user"}
                        </span>
                        <span style={{ marginLeft: "auto", fontSize: 9, color: "#8f8f8f" }}>{timeAgo(row.created_at)}</span>
                      </div>
                      <p style={{ fontSize: 11, color: "#737373", lineHeight: 1.5, margin: 0 }}>
                        {(row.text ?? "").slice(0, 90)}{(row.text ?? "").length > 90 ? "…" : ""}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Right col: recent chats + feedback */}
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

            {/* Feedback */}
            <div className="card" style={{ padding: "1.25rem" }}>
              <p className="section-label" style={{ marginBottom: 14 }}>Chatbot Feedback</p>
              {totalFb === 0 ? (
                <p style={{ fontSize: 12, color: "#8f8f8f" }}>No feedback yet — try the AI Chat page.</p>
              ) : (
                <>
                  <div style={{ display: "flex", gap: 10, marginBottom: 14 }}>
                    <div style={{ flex: 1, background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.15)", borderRadius: 10, padding: "10px", textAlign: "center" }}>
                      <div style={{ fontSize: 20, fontWeight: 700, color: "#22c55e" }}>{fb.thumbs_up}</div>
                      <div style={{ fontSize: 10, color: "#737373" }}>👍 Helpful</div>
                    </div>
                    <div style={{ flex: 1, background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.15)", borderRadius: 10, padding: "10px", textAlign: "center" }}>
                      <div style={{ fontSize: 20, fontWeight: 700, color: "#ef4444" }}>{fb.thumbs_down}</div>
                      <div style={{ fontSize: 10, color: "#737373" }}>👎 Not helpful</div>
                    </div>
                  </div>
                  {satisfactionPct != null && (
                    <div>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                        <span style={{ fontSize: 10, color: "#737373" }}>Satisfaction rate</span>
                        <span style={{ fontSize: 10, color: "#22c55e", fontWeight: 600 }}>{satisfactionPct}%</span>
                      </div>
                      <div style={{ height: 5, background: "rgba(0,0,0,0.05)", borderRadius: 99, overflow: "hidden" }}>
                        <div className="bar-grow" style={{ height: "100%", width: `${satisfactionPct}%`, background: "#22c55e", borderRadius: 99 }} />
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Recent chats */}
            <div className="card" style={{ padding: "1.25rem", flex: 1 }}>
              <p className="section-label" style={{ marginBottom: 14 }}>Recent Chat Queries</p>
              {chat.recent.length === 0 ? (
                <p style={{ fontSize: 12, color: "#8f8f8f" }}>No queries yet — try the AI Chat page.</p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                  {chat.recent.map((row: any) => (
                    <div key={row.id} style={{
                      padding: "8px 0",
                      borderBottom: "1px solid rgba(0,0,0,0.04)",
                      display: "flex", flexDirection: "column", gap: 3,
                    }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={{ fontSize: 9, color: "#3b82f6", background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.2)", padding: "1px 6px", borderRadius: 99 }}>
                          {row.mode}
                        </span>
                        <span style={{ marginLeft: "auto", fontSize: 9, color: "#8f8f8f" }}>{timeAgo(row.created_at)}</span>
                      </div>
                      <p style={{ fontSize: 11, color: "#737373", margin: 0, lineHeight: 1.5 }}>
                        {(row.question ?? "").slice(0, 72)}{(row.question ?? "").length > 72 ? "…" : ""}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>

          </div>
        </div>
      )}

      {/* Footer */}
      <div style={{ marginTop: 12, fontSize: 10, color: "#8f8f8f", textAlign: "right" }}>
        Last refreshed: {lastRefresh ? lastRefresh.toLocaleTimeString() : "—"}
      </div>
    </div>
  );
}

// ─── Official gov-data integration card ─────────────────────────────────────
const API_BASE = apiBase();

// ─── Live X ingestion card (honest counters — no fake activity) ──────────────
function LiveIngestionCard() {
  const [st, setSt] = useState<any>(null);
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
    fetch(`${API_BASE}/api/ingest/status`)
      .then(r => r.ok ? r.json() : null)
      .then(setSt)
      .catch(() => setSt(null));
  }, []);

  if (!st) return null;
  const live = st.configured;

  const items = [
    {
      label: "Feed Status",
      value: live ? "live" : "inactive",
      sub:   live ? `polls every ${st.poll_interval_minutes} min` : "X API token not configured",
      color: live ? "#22c55e" : "#737373",
    },
    {
      label: "Tweets Scanned",
      value: `${st.tweets_scanned}`,
      sub:   mounted && st.last_poll ? `last poll ${new Date(st.last_poll).toLocaleString()}` : "no polls yet",
      color: "#3b82f6",
    },
    {
      label: "Alerts Raised",
      value: `${st.alerts_raised}`,
      sub:   st.last_result ? `last result: ${st.last_result}` : "—",
      color: st.alerts_raised > 0 ? "#ef4444" : "#737373",
    },
  ];

  return (
    <div className="card anim-fade-up" style={{ padding: "1.1rem 1.25rem", marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <span style={{
          fontSize: 9, fontFamily: "var(--font-sans)", fontWeight: 700,
          color: live ? "#22c55e" : "#737373",
          background: live ? "rgba(34,197,94,0.12)" : "rgba(0,0,0,0.05)",
          border: `1px solid ${live ? "rgba(34,197,94,0.3)" : "rgba(0,0,0,0.1)"}`,
          padding: "2px 7px", borderRadius: 5,
        }}>X API</span>
        <span style={{ fontSize: 11, color: "#5f5f5f" }}>
          Live ingestion · public posts classified through the NLP pipeline
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10 }}>
        {items.map(it => (
          <div key={it.label} style={{ padding: "10px 12px", background: "rgba(0,0,0,0.025)", border: "1px solid rgba(0,0,0,0.05)", borderRadius: 8 }}>
            <div style={{ fontFamily: "var(--font-sans)", fontSize: 20, fontWeight: 700, color: it.color, marginBottom: 2 }}>
              {it.value}
            </div>
            <div style={{ fontSize: 11, fontWeight: 600, color: "#5f5f5f" }}>{it.label}</div>
            <div style={{ fontSize: 10, color: "#737373", marginTop: 2 }}>{it.sub}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function GovDataCard() {
  const [gd, setGd] = useState<any>(null);
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
    fetch(`${API_BASE}/api/govdata`)
      .then(r => r.ok ? r.json() : null)
      .then(setGd)
      .catch(() => setGd(null));
  }, []);

  if (!gd) return null;
  const s = gd.sources || {};
  const stations = s.gtfs_static;
  const ridership = s.ridership;
  const vehicles = s.vehicle_positions;

  // Ridership honesty: data.gov.my's headline series is years behind and only
  // some rail lines report. Surface BOTH facts rather than showing a bare
  // number that reads as current, network-wide ridership.
  const railVals = ridership?.rail
    ? Object.values(ridership.rail as Record<string, number | null>)
    : [];
  const reportedLines = railVals.filter((v): v is number => typeof v === "number");
  const ridershipTotal = reportedLines.reduce((a, b) => a + b, 0);
  const ridershipPartial = railVals.length > 0 && reportedLines.length < railVals.length;
  const ridershipAgeYears = ridership?.date
    ? (Date.now() - new Date(ridership.date).getTime()) / (365.25 * 24 * 3600 * 1000)
    : 0;
  const ridershipStale = ridershipAgeYears >= 1;

  const items = [
    {
      label: "Official Stations",
      value: stations?.ok ? `${stations.official_stop_count}` : "—",
      sub:   stations?.ok && stations.match
              ? `Matches local (${stations.local_stop_count})  ✓`
              : "data.gov.my GTFS Static",
      color: stations?.ok ? "#22c55e" : "#737373",
    },
    {
      label: "Daily Ridership (Rail)",
      value: ridershipTotal ? ridershipTotal.toLocaleString() : "—",
      sub:   ridership?.ok
              ? `as of ${ridership.date}`
              + (ridershipStale ? ` · ${Math.floor(ridershipAgeYears)} yrs old` : "")
              + (ridershipPartial
                  ? ` · only ${reportedLines.length} of ${railVals.length} lines report`
                  : "")
              : "ridership_headline",
      // amber = the number is real but NOT current/complete; don't let it read as live
      color: ridership?.ok && (ridershipStale || ridershipPartial) ? "#f59e0b" : "#3b82f6",
      warn:  ridership?.ok && (ridershipStale || ridershipPartial),
    },
    {
      label: "Realtime Vehicles",
      value: vehicles?.ok ? "live" : "n/a",
      sub:   vehicles?.ok
              ? "GTFS-RT feed online"
              : `feed unavailable${vehicles?.error ? ` (${String(vehicles.error).replace("HTTP Error ", "HTTP ")})` : ""}`,
      color: vehicles?.ok ? "#22c55e" : "#737373",
    },
  ];

  return (
    <div className="card anim-fade-up" style={{ padding: "1.1rem 1.25rem", marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <span style={{
          fontSize: 9, fontFamily: "var(--font-sans)", fontWeight: 700,
          color: "#22c55e", background: "rgba(34,197,94,0.12)",
          border: "1px solid rgba(34,197,94,0.3)",
          padding: "2px 7px", borderRadius: 5,
        }}>data.gov.my</span>
        <span style={{ fontSize: 11, color: "#5f5f5f" }}>
          Official integration · verified against Malaysian open data
        </span>
        <span style={{ marginLeft: "auto", fontSize: 9, color: "#8f8f8f" }}>
          {mounted && gd.fetched_at ? `cached ${new Date(gd.fetched_at).toLocaleString()}` : ""}
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10 }}>
        {items.map(it => (
          <div key={it.label} style={{ padding: "10px 12px", background: "rgba(0,0,0,0.025)", border: "1px solid rgba(0,0,0,0.05)", borderRadius: 8 }}>
            <div style={{ fontFamily: "var(--font-sans)", fontSize: 20, fontWeight: 700, color: it.color, marginBottom: 2 }}>
              {it.value}
            </div>
            <div style={{ fontSize: 11, fontWeight: 600, color: "#5f5f5f" }}>
              {it.label}
              {(it as any).warn && (
                <span title="Latest figure published by data.gov.my — not current"
                      style={{ marginLeft: 5, fontSize: 9, fontWeight: 700, color: "#b45309",
                               background: "rgba(245,158,11,0.12)",
                               border: "1px solid rgba(245,158,11,0.35)",
                               padding: "0 5px", borderRadius: 99 }}>
                  NOT CURRENT
                </span>
              )}
            </div>
            <div style={{ fontSize: 10, marginTop: 2,
                          color: (it as any).warn ? "#b45309" : "#737373" }}>{it.sub}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
