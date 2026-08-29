"use client";
import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import { getIncidents } from "@/lib/api";

const LINE_ORDER = ["KJ", "AG", "PH", "KGL", "PYL", "MR", "BRT", "SA"];

const WINDOWS: { label: string; hours: number }[] = [
  { label: "24 hours", hours: 24 },
  { label: "7 days",   hours: 168 },
  { label: "30 days",  hours: 720 },
];

const SOURCE_META: Record<string, { label: string; color: string; bd: string; bg: string }> = {
  x_official: { label: "✓ Official RapidKL", color: "#0369a1", bd: "#7dd3fc", bg: "#f0f9ff" },
  x_live:     { label: "X live",             color: "#5f5f5f", bd: "#cdcdcd", bg: "#ffffff" },
  voice:      { label: "voice report",       color: "#7c3aed", bd: "#ddd6fe", bg: "#faf5ff" },
  user:       { label: "user report",        color: "#5f5f5f", bd: "#cdcdcd", bg: "#ffffff" },
};

function timeAgo(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60)   return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function fullTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString([], {
      day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

export default function IncidentsPage() {
  const [data, setData]       = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [hours, setHours]     = useState(168);
  const [lineFilter, setLineFilter]     = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);

  const refresh = useCallback(async (h: number) => {
    setLoading(true);
    try {
      const d = await getIncidents(h);
      setData(d);
    } catch {
      // keep stale
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(hours); }, [hours, refresh]);

  const incidents: any[] = data?.incidents ?? [];

  // Counts per line / source across the loaded window (before filtering).
  const lineCounts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const it of incidents) if (it.detected_line) m[it.detected_line] = (m[it.detected_line] ?? 0) + 1;
    return m;
  }, [incidents]);

  const sourceCounts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const it of incidents) { const s = it.source ?? "user"; m[s] = (m[s] ?? 0) + 1; }
    return m;
  }, [incidents]);

  const filtered = incidents.filter(it =>
    (!lineFilter   || it.detected_line === lineFilter) &&
    (!sourceFilter || (it.source ?? "user") === sourceFilter)
  );

  return (
    <div className="anim-fade-up" style={{ maxWidth: 960 }}>

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <Link href="/status" style={{ fontSize: 12, color: "#737373", textDecoration: "none" }}>← Line Status</Link>
        <span className="section-label" style={{ margin: 0 }}>Incident History</span>
      </div>
      <h1 style={{ fontFamily: "var(--font-sans)", fontSize: 40, fontWeight: 400, letterSpacing: "-0.01em", color: "#000000", marginBottom: 12 }}>
        All Recent Incidents
      </h1>
      <p style={{ color: "#737373", fontSize: 13.5, lineHeight: 1.65, marginBottom: "1.5rem" }}>
        Every disruption alert logged from social reports, official RapidKL posts, in-app and voice
        reports — across all 8 rail lines. Filter by line or source below.
      </p>

      {data?.degraded && (
        <p style={{ fontSize: 12, color: "#b45309", background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.3)", borderRadius: 8, padding: "8px 12px", marginBottom: 12 }}>
          ⚠ Live data is temporarily unreachable — this list may be incomplete.
        </p>
      )}

      {/* Time window switch */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12, alignItems: "center" }}>
        <span style={{ fontSize: 11, color: "#8f8f8f", marginRight: 4 }}>Window:</span>
        {WINDOWS.map(w => (
          <button
            key={w.hours}
            onClick={() => setHours(w.hours)}
            className="pill-btn"
            style={{
              fontSize: 11,
              fontWeight: hours === w.hours ? 700 : 500,
              background: hours === w.hours ? "#000" : undefined,
              color: hours === w.hours ? "#fff" : undefined,
            }}
          >
            {w.label}
          </button>
        ))}
        <span style={{ marginLeft: "auto", fontSize: 11, color: "#8f8f8f" }}>
          {loading ? "Loading…" : `${filtered.length} shown${filtered.length !== incidents.length ? ` of ${incidents.length}` : ""}`}
        </span>
        <button onClick={() => refresh(hours)} className="pill-btn" style={{ fontSize: 10 }}>↻</button>
      </div>

      {/* Line filter buttons */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
        <button
          onClick={() => setLineFilter(null)}
          className="pill-btn"
          style={{ fontSize: 11, fontWeight: lineFilter === null ? 700 : 500, background: lineFilter === null ? "#000" : undefined, color: lineFilter === null ? "#fff" : undefined }}
        >
          All lines ({incidents.length})
        </button>
        {LINE_ORDER.filter(id => lineCounts[id]).map(id => {
          const active = lineFilter === id;
          return (
            <button
              key={id}
              onClick={() => setLineFilter(active ? null : id)}
              className="pill-btn"
              style={{ fontSize: 11, fontWeight: active ? 700 : 500, background: active ? "#000" : undefined, color: active ? "#fff" : undefined }}
            >
              {id} ({lineCounts[id]})
            </button>
          );
        })}
      </div>

      {/* Source filter buttons */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: "1.25rem" }}>
        <button
          onClick={() => setSourceFilter(null)}
          className="pill-btn"
          style={{ fontSize: 11, fontWeight: sourceFilter === null ? 700 : 500, background: sourceFilter === null ? "#000" : undefined, color: sourceFilter === null ? "#fff" : undefined }}
        >
          All sources
        </button>
        {Object.keys(sourceCounts).sort().map(s => {
          const active = sourceFilter === s;
          const sm = SOURCE_META[s] ?? SOURCE_META.user;
          return (
            <button
              key={s}
              onClick={() => setSourceFilter(active ? null : s)}
              className="pill-btn"
              style={{ fontSize: 11, fontWeight: active ? 700 : 500, background: active ? "#000" : undefined, color: active ? "#fff" : undefined }}
            >
              {sm.label} ({sourceCounts[s]})
            </button>
          );
        })}
      </div>

      {/* Incident list */}
      {loading && incidents.length === 0 ? (
        <div className="card" style={{ padding: "2rem", textAlign: "center" }}>
          <p style={{ fontSize: 12, color: "#8f8f8f" }}>Loading incidents…</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="card" style={{ padding: "2rem", textAlign: "center" }}>
          <p style={{ fontSize: 12, color: "#8f8f8f" }}>
            No incidents match this filter in the selected window.
          </p>
        </div>
      ) : (
        <div className="card" style={{ padding: "0.5rem 1.25rem" }}>
          {filtered.map((it, i) => {
            const sm = SOURCE_META[it.source ?? "user"] ?? SOURCE_META.user;
            return (
              <div key={it.id ?? i} style={{ display: "flex", alignItems: "flex-start", gap: 12, padding: "12px 0", borderBottom: i < filtered.length - 1 ? "1px solid rgba(0,0,0,0.05)" : "none" }}>
                {it.line_color && <div style={{ width: 3, alignSelf: "stretch", background: it.line_color, borderRadius: 99, flexShrink: 0, minHeight: 30 }} />}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", gap: 7, alignItems: "center", flexWrap: "wrap", marginBottom: 4 }}>
                    {it.detected_line && (
                      <span style={{ fontSize: 9, fontFamily: "var(--font-sans)", fontWeight: 700, color: it.line_color ?? "#000", background: `${it.line_color ?? "#000"}20`, border: `1px solid ${it.line_color ?? "#000"}35`, padding: "1px 7px", borderRadius: 4 }}>
                        {it.detected_line}
                      </span>
                    )}
                    {it.line_name && <span style={{ fontSize: 11, color: "#404040", fontWeight: 600 }}>{it.line_name}</span>}
                    <span style={{ fontSize: 10, fontWeight: 600, color: "#ef4444" }}>{it.issue_type}</span>
                    <span style={{ fontSize: 10, color: "#8f8f8f" }}>·</span>
                    <span style={{ fontSize: 10, color: "#8f8f8f" }}>{it.sentiment}</span>
                    <span style={{
                      marginLeft: "auto",
                      fontSize: 9, fontWeight: 600,
                      color: sm.color, border: `1px solid ${sm.bd}`, background: sm.bg,
                      padding: "1px 7px", borderRadius: 99,
                    }}>
                      {sm.label}
                    </span>
                  </div>
                  <p style={{ fontSize: 12.5, color: "#404040", lineHeight: 1.5, marginBottom: 4 }}>
                    {it.text}
                  </p>
                  <p style={{ fontSize: 10, color: "#a3a3a3" }}>
                    {fullTime(it.created_at)} · {timeAgo(it.created_at)}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div style={{ marginTop: 16 }}>
        <Link href="/status" className="pill-btn" style={{ fontSize: 12 }}>← Back to Line Status</Link>
      </div>
    </div>
  );
}
