"use client";
import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { getLineStatus, detectDisruption } from "@/lib/api";
import LiveRegion from "@/components/LiveRegion";

const STATUS_CFG = {
  disrupted:   { label: "DISRUPTED",   color: "#ef4444", bg: "rgba(239,68,68,0.12)",  bd: "rgba(239,68,68,0.35)",  dot: "#ef4444", pulse: true  },
  unconfirmed: { label: "UNCONFIRMED", color: "#f59e0b", bg: "rgba(245,158,11,0.06)", bd: "rgba(245,158,11,0.25)", dot: "#f59e0b", pulse: false },
  recovering:  { label: "RECOVERING",  color: "#f59e0b", bg: "rgba(245,158,11,0.1)",  bd: "rgba(245,158,11,0.3)",  dot: "#f59e0b", pulse: false },
  normal:      { label: "NORMAL",      color: "#22c55e", bg: "rgba(34,197,94,0.08)",   bd: "rgba(34,197,94,0.2)",   dot: "#22c55e", pulse: false },
};

const LINE_ORDER = ["KJ", "AG", "PH", "KGL", "PYL", "MR", "BRT", "SA"];

function timeAgo(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60)  return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

export default function StatusPage() {
  const [data, setData]         = useState<any>(null);
  const [loading, setLoading]   = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [simText, setSimText]   = useState("");
  const [simming, setSimming]   = useState(false);
  const [simResult, setSimResult] = useState<any>(null);

  const refresh = useCallback(async () => {
    try {
      const d = await getLineStatus();
      setData(d);
      setLastRefresh(new Date());
    } catch {
      // backend offline — keep showing stale data
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  const simulate = async () => {
    if (!simText.trim()) return;
    setSimming(true); setSimResult(null);
    try {
      const r = await detectDisruption(simText);
      setSimResult(r);
      // Refresh status after 1s so Supabase write propagates
      setTimeout(refresh, 1200);
    } finally {
      setSimming(false);
    }
  };

  const lines = data?.lines ?? {};
  const feed: any[]  = data?.recent_feed ?? [];

  const disruptedCount   = LINE_ORDER.filter(id => lines[id]?.status === "disrupted").length;
  const recoveringCount  = LINE_ORDER.filter(id => lines[id]?.status === "recovering").length;
  const unconfirmedCount = LINE_ORDER.filter(id => lines[id]?.status === "unconfirmed").length;

  // The board auto-refreshes every 30s. Announce only ABNORMAL lines: reading
  // out all eight on every poll would make the page unusable with a screen
  // reader, and "everything is fine" is not news worth interrupting for.
  const announcement = (() => {
    const lines: any[] = Object.values(data?.lines ?? {});
    const bad = lines.filter(l => l.status === "disrupted" || l.status === "unconfirmed");
    if (!data || !bad.length) return "";
    // Cap the utterance: on a bad day every line could be lit, and a
    // 30-second auto-refresh reading eight of them makes the page unusable.
    const spoken = bad.slice(0, 3)
      .map(l => `${l.name} is ${l.status === "disrupted" ? "disrupted" : "reported, unconfirmed"}`
                + (l.affected_stations?.length ? ` at ${l.affected_stations.join(", ")}` : ""))
      .join(". ");
    const rest = bad.length - 3;
    return rest > 0 ? `${spoken}. And ${rest} more line${rest > 1 ? "s" : ""}.` : `${spoken}.`;
  })();

  return (
    <div className="anim-fade-up" style={{ maxWidth: 960 }}>
      <LiveRegion message={announcement} />

      <p className="section-label" style={{ marginBottom: 8 }}>Live Monitoring · 8 Rail Lines · Auto-refresh 30s</p>
      <h1 style={{ fontFamily: "var(--font-sans)", fontSize: 40, fontWeight: 400, letterSpacing: "-0.01em", color: "#000000", marginBottom: 12 }}>
        Public Transit Status Board
      </h1>
      <p style={{ color: "#737373", fontSize: 13.5, lineHeight: 1.65, marginBottom: "1rem" }}>
        Real-time disruption monitoring derived from logged social reports. Status updates whenever a disruption alert is detected.
      </p>

      {/* Sub-tabs: live board vs full history */}
      <div style={{ display: "flex", gap: 6, marginBottom: "1.5rem", borderBottom: "1px solid rgba(0,0,0,0.08)", paddingBottom: 2 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: "#000", padding: "6px 12px", borderBottom: "2px solid #000", marginBottom: -3 }}>
          Live Board
        </span>
        <Link
          href="/incidents"
          style={{ fontSize: 12.5, fontWeight: 500, color: "#737373", textDecoration: "none", padding: "6px 12px", marginBottom: -3, borderBottom: "2px solid transparent" }}
        >
          All Incidents →
        </Link>
      </div>

      {data?.degraded && (
        <p style={{ fontSize: 12, color: "#b45309", background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.3)", borderRadius: 8, padding: "8px 12px", marginBottom: 12 }}>
          ⚠ Live data is temporarily unreachable — statuses below may be out of date. Refreshing automatically.
        </p>
      )}

      {/* Summary bar */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: "1.5rem", alignItems: "center" }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: "#22c55e", background: "rgba(34,197,94,0.1)", border: "1px solid rgba(34,197,94,0.25)", padding: "4px 12px", borderRadius: 99 }}>
          {LINE_ORDER.length - disruptedCount - recoveringCount - unconfirmedCount} lines normal
        </span>
        {unconfirmedCount > 0 && (
          <span style={{ fontSize: 11, fontWeight: 600, color: "#b45309", background: "rgba(245,158,11,0.06)", border: "1px dashed rgba(245,158,11,0.35)", padding: "4px 12px", borderRadius: 99 }}>
            👀 {unconfirmedCount} unconfirmed
          </span>
        )}
        {recoveringCount > 0 && (
          <span style={{ fontSize: 11, fontWeight: 600, color: "#f59e0b", background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.25)", padding: "4px 12px", borderRadius: 99 }}>
            {recoveringCount} recovering
          </span>
        )}
        {disruptedCount > 0 && (
          <span className="pulse-red" style={{ fontSize: 11, fontWeight: 700, color: "#fff", background: "#ef4444", padding: "4px 12px", borderRadius: 99 }}>
            🚨 {disruptedCount} disrupted
          </span>
        )}
        <span style={{ marginLeft: "auto", fontSize: 10, color: "#8f8f8f" }}>
          {lastRefresh ? `Updated ${timeAgo(lastRefresh.toISOString())}` : "Loading…"}
        </span>
        <button onClick={refresh} className="pill-btn" style={{ fontSize: 10 }}>↻ Refresh</button>
      </div>

      {/* Line grid */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: "1.5rem" }}>
        {LINE_ORDER.map(lineId => {
          const line = lines[lineId];
          if (!line) {
            // Skeleton while loading
            return (
              <div key={lineId} className="card" style={{ padding: "1rem 1.1rem", opacity: 0.4 }}>
                <div style={{ height: 12, background: "rgba(0,0,0,0.06)", borderRadius: 6, marginBottom: 8, width: "60%" }} />
                <div style={{ height: 8, background: "rgba(0,0,0,0.04)", borderRadius: 4, width: "40%" }} />
              </div>
            );
          }
          const sc = STATUS_CFG[line.status as keyof typeof STATUS_CFG] ?? STATUS_CFG.normal;
          return (
            <div key={lineId} className="card" style={{
              padding: "1rem 1.1rem",
              borderColor: sc.bd,
              background: sc.bg,
              transition: "all 0.4s",
            }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                {/* Colour bar */}
                <div style={{ width: 4, alignSelf: "stretch", background: line.color, borderRadius: 99, flexShrink: 0, minHeight: 36 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 5 }}>
                    <span style={{ fontSize: 9, fontFamily: "var(--font-sans)", fontWeight: 700, color: line.color, background: `${line.color}20`, border: `1px solid ${line.color}35`, padding: "2px 7px", borderRadius: 5 }}>{lineId}</span>
                    <span style={{ fontSize: 12, color: "#000000", fontWeight: 600, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{line.name}</span>
                  </div>

                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{
                      width: 7, height: 7, borderRadius: "50%", background: sc.dot, flexShrink: 0,
                      boxShadow: sc.pulse ? `0 0 6px ${sc.dot}` : "none",
                    }} />
                    <span style={{ fontSize: 10, fontWeight: 700, color: sc.color, letterSpacing: "0.06em" }}>{sc.label}</span>
                  </div>

                  {line.alert_count_4h > 0 && (
                    <p style={{ fontSize: 10, color: "#737373", marginTop: 5 }}>
                      {line.alert_count_4h} alert{line.alert_count_4h !== 1 ? "s" : ""} in last 4h
                      {line.last_alert && ` · last ${timeAgo(line.last_alert.created_at)}`}
                    </p>
                  )}

                  {/* Station drill-down: WHICH station(s) on this line are reported.
                      "Kelana Jaya — issue at Masjid Jamek" instead of a bare red line. */}
                  {line.affected_stations?.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6, alignItems: "center" }}>
                      <span style={{ fontSize: 10, color: "#5f5f5f" }}>Reported at:</span>
                      {line.affected_stations.map((st: string) => (
                        <span key={st} style={{ fontSize: 9, fontWeight: 700, color: sc.color, background: sc.bg, border: `1px solid ${sc.bd}`, padding: "1px 6px", borderRadius: 99 }}>
                          📍 {st}
                        </span>
                      ))}
                    </div>
                  )}
                  {line.last_alert && (
                    <p style={{ fontSize: 10, color: "#8f8f8f", marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      "{line.last_alert.text?.slice(0, 55)}{(line.last_alert.text?.length ?? 0) > 55 ? "…" : ""}"
                    </p>
                  )}
                  {line.alert_count_4h === 0 && (
                    <p style={{ fontSize: 10, color: "#8f8f8f", marginTop: 5 }}>No incidents in last 4 hours</p>
                  )}

                  {line.status === "unconfirmed" && (
                    <p style={{ fontSize: 10, color: "#b45309", marginTop: 5 }}>
                      Unverified — corroboration <strong>{line.corroboration}</strong>
                      {" / "}{line.confirm_weight ?? 2} needed. Shown, not acted on.
                    </p>
                  )}
                  {line.status === "disrupted" && line.corroboration != null && (
                    <p style={{ fontSize: 10, color: "#737373", marginTop: 5 }}>
                      Confirmed — corroboration <strong>{line.corroboration}</strong>
                      {" / "}{line.confirm_weight ?? 2}
                    </p>
                  )}
                  {(line.status === "disrupted" || line.status === "recovering" || line.status === "unconfirmed") && (
                    <Link
                      href={`/reroute?avoid=${lineId}`}
                      style={{
                        display: "inline-block", marginTop: 8,
                        fontSize: 10, fontWeight: 600,
                        color: sc.color, textDecoration: "none",
                        padding: "4px 9px", borderRadius: 5,
                        background: `${sc.dot}15`,
                        border: `1px solid ${sc.dot}30`,
                      }}
                    >
                      Plan around this →
                    </Link>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Simulate disruption */}
      <div className="card" style={{ padding: "1.25rem", marginBottom: 12 }}>
        <p style={{ fontSize: 11, color: "#737373", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10 }}>
          Simulate Disruption Report
        </p>
        <p style={{ fontSize: 12, color: "#8f8f8f", marginBottom: 12 }}>
          Submit a social post — the NLP agent classifies it and if it's an alert, the line status updates automatically.
        </p>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
          {[
            "Kelana Jaya line completely broken down at KLCC, trains not moving!",
            "Ampang line delayed 30 minutes, platform packed with commuters.",
            "MRT Kajang service back to normal after earlier fault.",
          ].map(ex => (
            <button key={ex} onClick={() => setSimText(ex)} className="pill-btn" style={{ fontSize: 10 }}>
              {ex.slice(0, 40)}…
            </button>
          ))}
        </div>
        <textarea
          className="textarea"
          style={{ height: 72, marginBottom: 10 }}
          placeholder="Type a disruption report to test the monitoring pipeline…"
          value={simText}
          onChange={e => setSimText(e.target.value)}
        />
        <button className="btn-primary" onClick={simulate} disabled={simming || !simText.trim()}>
          {simming
            ? <><span className="anim-spin" style={{ width: 12, height: 12, border: "2px solid rgba(255,255,255,0.4)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block" }} /> Submitting…</>
            : "Submit Report →"}
        </button>
        {simResult && (
          <div className="anim-fade-in" style={{
            marginTop: 12,
            padding: "10px 14px",
            background: simResult.disruption_alert ? "rgba(239,68,68,0.08)" : "rgba(34,197,94,0.08)",
            border: `1px solid ${simResult.disruption_alert ? "rgba(239,68,68,0.25)" : "rgba(34,197,94,0.25)"}`,
            borderRadius: 10,
            fontSize: 12,
            color: simResult.disruption_alert ? "#ef4444" : "#22c55e",
          }}>
            {simResult.disruption_alert
              ? `🚨 Alert detected — ${simResult.issue_type} · ${simResult.sentiment} sentiment`
              : `✅ No disruption — ${simResult.issue_type} · ${simResult.sentiment} sentiment`}
            {simResult.method === "gemini_fallback" && <span style={{ marginLeft: 8, fontSize: 10, color: "#a855f7" }}>✦ Gemini fallback</span>}
          </div>
        )}
      </div>

      {/* Recent incident feed */}
      {feed.length > 0 && (
        <div className="card" style={{ padding: "1.25rem", marginBottom: 12 }}>
          <p style={{ fontSize: 10, color: "#737373", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 }}>Recent Incidents Gathered from Multiple Sources (Last 4h)</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {feed.map((item: any, i: number) => {
              const lm = lines[item.detected_line];
              return (
                <div key={item.id ?? i} style={{ display: "flex", alignItems: "flex-start", gap: 10, padding: "8px 0", borderBottom: i < feed.length - 1 ? "1px solid rgba(0,0,0,0.04)" : "none" }}>
                  {lm && <div style={{ width: 3, alignSelf: "stretch", background: lm.color, borderRadius: 99, flexShrink: 0 }} />}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 3 }}>
                      {lm && <span style={{ fontSize: 9, fontFamily: "var(--font-sans)", fontWeight: 700, color: lm.color, background: `${lm.color}20`, border: `1px solid ${lm.color}30`, padding: "1px 6px", borderRadius: 4 }}>{item.detected_line}</span>}
                      {/* Interchange / multi-line station: no single line, show the station name */}
                      {!lm && item.detected_station && <span style={{ fontSize: 9, fontWeight: 700, color: "#5f5f5f", background: "#f0f0f0", border: "1px solid #cdcdcd", padding: "1px 6px", borderRadius: 4 }}>📍 {item.detected_station}</span>}
                      <span style={{ fontSize: 10, fontWeight: 600, color: "#ef4444" }}>{item.issue_type}</span>
                      <span style={{ fontSize: 10, color: "#8f8f8f" }}>·</span>
                      <span style={{ fontSize: 10, color: "#8f8f8f" }}>{timeAgo(item.created_at)}</span>
                      <span style={{
                        fontSize: 9, fontWeight: 600,
                        color: item.source === "x_official" ? "#0369a1" : "#5f5f5f",
                        border: `1px solid ${item.source === "x_official" ? "#7dd3fc" : "#cdcdcd"}`,
                        background: item.source === "x_official" ? "#f0f9ff" : "#ffffff",
                        padding: "1px 7px", borderRadius: 99,
                      }}>
                        {item.source === "x_official" ? "✓ Official RapidKL"
                          : item.source === "x_live" ? "X live" : "user report"}
                      </span>
                    </div>
                    <p style={{ fontSize: 11, color: "#737373", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {item.text}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {feed.length === 0 && !loading && (
        <div className="card" style={{ padding: "1rem 1.25rem", textAlign: "center" }}>
          <p style={{ fontSize: 12, color: "#8f8f8f", marginBottom: 10 }}>No incidents logged in the last 4 hours. Use the simulator above to generate test data.</p>
          <Link
            href="/incidents"
            style={{
              fontSize: 11, fontWeight: 600, color: "#000", textDecoration: "none",
              padding: "5px 12px", borderRadius: 99,
              background: "rgba(0,0,0,0.05)", border: "1px solid rgba(0,0,0,0.12)",
            }}
          >
            View all incidents (up to 30 days) →
          </Link>
        </div>
      )}

      {/* Meta */}
      <div className="card" style={{ marginTop: 12, padding: "0.7rem 1.1rem", display: "flex", flexWrap: "wrap", gap: "1rem" }}>
        {[["Lines","8 rail lines"],["Status refresh","30s"],["Alert window","30 min"],["Recovery window","4 hours"]].map(([k,v]) => (
          <span key={k} style={{ fontSize: 10 }}>
            <span style={{ color: "#8f8f8f" }}>{k}: </span>
            <span style={{ color: "#737373" }}>{v}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
