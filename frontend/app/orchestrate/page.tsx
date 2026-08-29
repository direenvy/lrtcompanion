"use client";
import { useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { runOrchestrator, friendlyError } from "@/lib/api";
import ReactMarkdown from "react-markdown";

const RouteMap = dynamic(() => import("@/components/RouteMap"), { ssr: false });

const LINE_CFG: Record<string, { color: string; name: string }> = {
  KJ:  { color: "#ef4444", name: "Kelana Jaya" },
  AG:  { color: "#f97316", name: "Ampang" },
  PH:  { color: "#ec4899", name: "Sri Petaling" },
  KGL: { color: "#22c55e", name: "MRT Kajang" },
  PYL: { color: "#eab308", name: "MRT Putrajaya" },
  MR:  { color: "#84cc16", name: "Monorail" },
  BRT: { color: "#10b981", name: "BRT Sunway" },
};

const SENTIMENT_COLOR: Record<string, string> = {
  negative: "#ef4444",
  neutral:  "#f59e0b",
  positive: "#22c55e",
};

const EXAMPLES = [
  {
    text: "Kelana Jaya line breakdown at KLCC, trains stuck for 40 minutes!",
    origin: "MASJID JAMEK", dest: "PUTRA HEIGHTS", disrupted: "KJ15",
  },
  {
    text: "MRT Kajang severely delayed from Bukit Dukung, nightmare commute.",
    origin: "KL SENTRAL", dest: "KAJANG", disrupted: "",
  },
  {
    text: "Service running fine today, no issues at all.",
    origin: "KLCC", dest: "GOMBAK", disrupted: "",
  },
];

type AgentStatus = "idle" | "running" | "done" | "skipped";

interface PipelineState {
  nlp:    AgentStatus;
  route:  AgentStatus;
  rag:    AgentStatus;
}

export default function OrchestratePage() {
  const [text, setText]           = useState("");
  const [origin, setOrigin]       = useState("");
  const [dest, setDest]           = useState("");
  const [disrupted, setDisrupted] = useState("");
  const [result, setResult]       = useState<any>(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState("");
  const [pipeline, setPipeline]   = useState<PipelineState>({ nlp: "idle", route: "idle", rag: "idle" });
  const [expanded, setExpanded]   = useState<Record<number, boolean>>({});

  const toggleExpand = (i: number) =>
    setExpanded(prev => ({ ...prev, [i]: !prev[i] }));

  const fillExample = (ex: typeof EXAMPLES[0]) => {
    setText(ex.text);
    setOrigin(ex.origin);
    setDest(ex.dest);
    setDisrupted(ex.disrupted);
  };

  const run = async () => {
    if (!text.trim()) return;
    setLoading(true); setError(""); setResult(null);
    setPipeline({ nlp: "idle", route: "idle", rag: "idle" });

    // Animate pipeline steps
    setPipeline({ nlp: "running", route: "idle", rag: "idle" });
    await new Promise(r => setTimeout(r, 600));
    setPipeline({ nlp: "done", route: "running", rag: "idle" });
    await new Promise(r => setTimeout(r, 500));
    setPipeline({ nlp: "done", route: "done", rag: "running" });

    try {
      const dis = disrupted.split(",").map(s => s.trim()).filter(Boolean);
      const data = await runOrchestrator(
        text,
        origin.toUpperCase(),
        dest.toUpperCase(),
        dis
      );
      setPipeline({ nlp: "done", route: data.reroute ? "done" : "skipped", rag: "done" });
      setResult(data);
    } catch (e) {
      setError(friendlyError(e));
      setPipeline({ nlp: "idle", route: "idle", rag: "idle" });
    } finally {
      setLoading(false);
    }
  };

  const statusDot = (s: AgentStatus) => {
    if (s === "running") return <span className="anim-spin" style={{ width: 10, height: 10, border: "2px solid rgba(0,0,0,0.15)", borderTopColor: "#22c55e", borderRadius: "50%", display: "inline-block" }} />;
    if (s === "done")    return <span style={{ color: "#22c55e", fontSize: 13 }}>✓</span>;
    if (s === "skipped") return <span style={{ color: "#737373", fontSize: 11 }}>—</span>;
    return <span style={{ width: 6, height: 6, borderRadius: "50%", background: "rgba(0,0,0,0.1)", display: "inline-block" }} />;
  };

  const nlp     = result?.nlp;
  const reroute = result?.reroute;
  const rag     = result?.rag;

  return (
    <div className="anim-fade-up" style={{ maxWidth: 960 }}>

      {/* This page is reached from Dashboard rather than the main nav, so it
          carries its own way back — otherwise the only exit is the browser. */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <Link href="/dashboard" style={{ fontSize: 12, color: "#737373", textDecoration: "none" }}>← Dashboard</Link>
        <span className="section-label" style={{ margin: 0 }}>Multi-Agent Orchestrator · 3 Agents in Sequence</span>
      </div>
      <h1 style={{ fontFamily: "var(--font-sans)", fontSize: 40, fontWeight: 400, letterSpacing: "-0.01em", color: "#000000", marginBottom: 12 }}>
        Advanced Recovery Planner
      </h1>
      <p style={{ color: "#737373", fontSize: 13.5, lineHeight: 1.65, marginBottom: "2rem" }}>
        A single disruption report triggers all three agents — NLP detection, smart rerouting, and RAG-grounded advice — in one coordinated pipeline.
      </p>

      {/* Pipeline visualiser */}
      <div style={{ display: "flex", alignItems: "center", gap: 0, marginBottom: "1.75rem" }}>
        {[
          { key: "nlp",   label: "NLP Agent",      sub: "Detect",   color: "#ef4444" },
          { key: "route", label: "Route Agent",     sub: "Reroute",  color: "#3b82f6" },
          { key: "rag",   label: "RAG Agent",       sub: "Advise",   color: "#22c55e" },
        ].map((agent, idx) => {
          const s = pipeline[agent.key as keyof PipelineState];
          const active = s === "running" || s === "done";
          return (
            <div key={agent.key} style={{ display: "flex", alignItems: "center", flex: 1 }}>
              <div style={{
                flex: 1, background: active ? `${agent.color}12` : "rgba(0,0,0,0.03)",
                border: `1px solid ${active ? agent.color + "30" : "rgba(0,0,0,0.06)"}`,
                borderRadius: 10, padding: "10px 14px",
                transition: "all 0.3s",
                display: "flex", alignItems: "center", gap: 10,
              }}>
                <span style={{ width: 18, display: "flex", alignItems: "center", justifyContent: "center" }}>
                  {statusDot(s)}
                </span>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: active ? agent.color : "#737373" }}>{agent.label}</div>
                  <div style={{ fontSize: 10, color: "#8f8f8f" }}>{agent.sub}</div>
                </div>
              </div>
              {idx < 2 && (
                <div style={{ width: 24, display: "flex", alignItems: "center", justifyContent: "center", color: "#2d2d2d", fontSize: 14, flexShrink: 0 }}>→</div>
              )}
            </div>
          );
        })}
      </div>

      {/* Input */}
      <div className="card" style={{ padding: "1.5rem", marginBottom: 12 }}>

        {/* Examples */}
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
          {EXAMPLES.map((ex, i) => (
            <button key={i} onClick={() => fillExample(ex)} className="pill-btn">
              Example {i + 1}: {ex.text.slice(0, 32)}…
            </button>
          ))}
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 10, color: "#737373", display: "block", marginBottom: 5, letterSpacing: "0.08em", textTransform: "uppercase" }}>Disruption Report</label>
          <textarea
            className="textarea"
            style={{ height: 80 }}
            placeholder="e.g. Kelana Jaya line breakdown at KLCC, stuck 40 mins!"
            value={text}
            onChange={e => setText(e.target.value)}
          />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>
          {([ ["Origin", origin, setOrigin, "e.g. KLCC"], ["Destination", dest, setDest, "e.g. PUTRA HEIGHTS"] ] as const).map(([label, val, set, ph]) => (
            <div key={label}>
              <label style={{ fontSize: 10, color: "#737373", display: "block", marginBottom: 5, letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</label>
              <input className="input" placeholder={ph} value={val} onChange={e => set(e.target.value)} />
            </div>
          ))}
        </div>

        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 10, color: "#737373", display: "block", marginBottom: 5, letterSpacing: "0.08em", textTransform: "uppercase" }}>
            Disrupted Stop IDs <span style={{ color: "#8f8f8f", textTransform: "none" }}>(optional · comma-separated)</span>
          </label>
          <input className="input" style={{ borderColor: "rgba(239,68,68,0.15)" }}
            placeholder="e.g. KJ15, KJ16"
            value={disrupted} onChange={e => setDisrupted(e.target.value)}
          />
        </div>

        <button className="btn-primary" onClick={run} disabled={loading || !text.trim()}>
          {loading
            ? <><span className="anim-spin" style={{ width: 13, height: 13, border: "2px solid rgba(255,255,255,0.4)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block" }} /> Running pipeline…</>
            : "Run Pipeline →"}
        </button>

        {error && (
          <div className="anim-fade-in" style={{ marginTop: 14, background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 10, padding: "10px 14px", display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ color: "#ef4444", fontSize: 12, flex: 1 }}>{error}</span>
            <button className="pill-btn" onClick={() => run()} style={{ fontSize: 11, flexShrink: 0 }}>↻ Retry</button>
          </div>
        )}
      </div>

      {/* Results */}
      {loading && !result && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 12 }}>
          {["Detecting the issue…", "Finding your route…", "Preparing advice…"].map((label) => (
            <div key={label} className="card anim-fade-in" style={{ padding: "1.25rem" }}>
              <p className="section-label" style={{ marginBottom: 10 }}>{label}</p>
              <div style={{ height: 12, width: "70%", background: "rgba(0,0,0,0.05)", borderRadius: 5, marginBottom: 8 }} />
              <div style={{ height: 12, width: "45%", background: "rgba(0,0,0,0.05)", borderRadius: 5 }} />
            </div>
          ))}
        </div>
      )}

      {result && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

          {/* Summary banner */}
          <div className="card anim-fade-up" style={{
            padding: "1rem 1.25rem",
            background: result.disruption_alert ? "rgba(239,68,68,0.06)" : "rgba(34,197,94,0.06)",
            borderColor: result.disruption_alert ? "rgba(239,68,68,0.2)" : "rgba(34,197,94,0.2)",
          }}>
            <p style={{ fontSize: 13, color: result.disruption_alert ? "#ef4444" : "#22c55e", fontWeight: 500 }}>
              {result.summary}
            </p>
          </div>

          {/* Agent 1: NLP */}
          {nlp && (
            <div className="card anim-fade-up" style={{ padding: "1.25rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                <span style={{ fontSize: 9, fontFamily: "var(--font-sans)", fontWeight: 700, color: "#ef4444", background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", padding: "2px 8px", borderRadius: 5 }}>AGENT 1</span>
                <span style={{ fontSize: 12, color: "#5f5f5f", fontWeight: 500 }}>NLP Detection</span>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: SENTIMENT_COLOR[nlp.sentiment] ?? "#737373", background: `${SENTIMENT_COLOR[nlp.sentiment] ?? "#737373"}18`, border: `1px solid ${SENTIMENT_COLOR[nlp.sentiment] ?? "#737373"}30`, padding: "3px 10px", borderRadius: 99 }}>
                  {nlp.sentiment}
                </span>
                <span style={{ fontSize: 11, fontWeight: 600, color: "#3b82f6", background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.2)", padding: "3px 10px", borderRadius: 99 }}>
                  {nlp.issue_type}
                </span>
                {nlp.disruption_alert
                  ? <span className="pulse-red" style={{ fontSize: 11, fontWeight: 700, color: "#fff", background: "#ef4444", padding: "3px 10px", borderRadius: 99 }}>🚨 Alert</span>
                  : <span style={{ fontSize: 11, color: "#737373", background: "rgba(0,0,0,0.04)", border: "1px solid rgba(0,0,0,0.07)", padding: "3px 10px", borderRadius: 99 }}>✅ No Alert</span>
                }
                {nlp.method === "gemini_fallback" && (
                  <span style={{ fontSize: 10, color: "#a855f7", background: "rgba(168,85,247,0.1)", border: "1px solid rgba(168,85,247,0.25)", padding: "3px 10px", borderRadius: 99 }}>✦ Gemini fallback</span>
                )}
              </div>
              {/* Mini confidence bars */}
              {nlp.sentiment_scores && (
                <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
                  {Object.entries(nlp.sentiment_scores as Record<string, number>)
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([label, pct]) => (
                      <div key={label} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ width: 52, fontSize: 10, color: "#737373", textAlign: "right", textTransform: "capitalize" }}>{label}</span>
                        <div style={{ flex: 1, height: 4, background: "rgba(0,0,0,0.05)", borderRadius: 99, overflow: "hidden" }}>
                          <div className="bar-grow" style={{ height: "100%", width: `${pct}%`, background: SENTIMENT_COLOR[label] ?? "#737373", borderRadius: 99 }} />
                        </div>
                        <span style={{ width: 32, fontSize: 10, color: "#8f8f8f", textAlign: "right" }}>{pct}%</span>
                      </div>
                    ))}
                </div>
              )}
            </div>
          )}

          {/* Agent 2: Rerouting */}
          <div className="card anim-fade-up" style={{ padding: "1.25rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
              <span style={{ fontSize: 9, fontFamily: "var(--font-sans)", fontWeight: 700, color: "#3b82f6", background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.2)", padding: "2px 8px", borderRadius: 5 }}>AGENT 2</span>
              <span style={{ fontSize: 12, color: "#5f5f5f", fontWeight: 500 }}>Smart Rerouting</span>
            </div>
            {reroute && !reroute.error ? (() => {
              const segs: any[] = reroute.segments ?? reroute.steps?.map((s: any) => ({
                ...s, stations: [s.from, s.to], n_stops: 1, minutes: null,
              })) ?? [];
              return (
                <>
                  <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginBottom: 14 }}>
                    {[
                      { label: `${reroute.origin} → ${reroute.destination}`, color: "#000000", bg: "rgba(0,0,0,0.05)", bd: "rgba(0,0,0,0.1)" },
                      { label: `${reroute.total_stops} stops`,              color: "#3b82f6", bg: "rgba(59,130,246,0.1)",   bd: "rgba(59,130,246,0.25)" },
                      { label: `~${reroute.estimated_minutes} min`,         color: "#22c55e", bg: "rgba(34,197,94,0.1)",    bd: "rgba(34,197,94,0.25)" },
                      ...(reroute.interchanges > 0
                        ? [{ label: `${reroute.interchanges} transfer${reroute.interchanges > 1 ? "s" : ""}`, color: "#f59e0b", bg: "rgba(245,158,11,0.1)", bd: "rgba(245,158,11,0.25)" }]
                        : [{ label: "Direct", color: "#22c55e", bg: "rgba(34,197,94,0.08)", bd: "rgba(34,197,94,0.2)" }]),
                      ...(reroute.disrupted_stops_avoided?.length > 0
                        ? [{ label: `${reroute.disrupted_stops_avoided.length} avoided`, color: "#ef4444", bg: "rgba(239,68,68,0.1)", bd: "rgba(239,68,68,0.25)" }]
                        : []),
                    ].map(b => (
                      <span key={b.label} style={{ fontSize: 10, fontWeight: 600, color: b.color, background: b.bg, border: `1px solid ${b.bd}`, padding: "3px 10px", borderRadius: 99 }}>{b.label}</span>
                    ))}
                  </div>

                  {/* Map */}
                  {segs.some((s: any) => s.station_points?.length >= 2) && (
                    <div style={{ height: 280, borderRadius: 10, overflow: "hidden", marginBottom: 16, border: "1px solid rgba(0,0,0,0.07)" }}>
                      <RouteMap
                        segments={segs}
                        disrupted_avoided={reroute.disrupted_stops_avoided ?? []}
                      />
                    </div>
                  )}

                  <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                    {segs.map((seg: any, si: number) => {
                      const cfg    = LINE_CFG[seg.line] ?? { color: "#737373", name: seg.line };
                      const isOpen = !!expanded[si];
                      const stations: string[] = seg.stations ?? [seg.from, seg.to];
                      const isLast = si === segs.length - 1;
                      return (
                        <div key={si}>
                          {si > 0 && (
                            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0 6px 18px" }}>
                              <div style={{ width: 2, background: "rgba(0,0,0,0.06)", alignSelf: "stretch" }} />
                              <span style={{ fontSize: 10, fontWeight: 600, color: "#f59e0b", background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.25)", padding: "2px 9px", borderRadius: 99 }}>⇄ Transfer at {seg.from}</span>
                            </div>
                          )}
                          <button
                            onClick={() => toggleExpand(si)}
                            style={{ width: "100%", background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 10, padding: "8px 0", textAlign: "left", borderBottom: isOpen ? "none" : (isLast ? "none" : "1px solid rgba(0,0,0,0.04)") }}
                          >
                            <div style={{ width: 3, alignSelf: "stretch", background: cfg.color, borderRadius: 99, flexShrink: 0 }} />
                            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 3 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <span style={{ fontSize: 9, fontFamily: "var(--font-sans)", fontWeight: 700, color: cfg.color, background: `${cfg.color}18`, border: `1px solid ${cfg.color}30`, padding: "2px 7px", borderRadius: 5, flexShrink: 0 }}>{cfg.name}</span>
                                <span style={{ fontSize: 11, color: "#000000", fontWeight: 600 }}>{seg.from}</span>
                                <span style={{ color: "#8f8f8f", fontSize: 10 }}>→</span>
                                <span style={{ fontSize: 11, color: "#000000", fontWeight: 600 }}>{seg.to}</span>
                              </div>
                              <span style={{ fontSize: 10, color: "#737373", paddingLeft: 2 }}>
                                {seg.n_stops} stop{seg.n_stops !== 1 ? "s" : ""}
                                {seg.minutes ? ` · ~${seg.minutes} min` : ""}
                                {" · "}<span style={{ color: cfg.color }}>{isOpen ? "▲ hide" : "▼ show stations"}</span>
                              </span>
                            </div>
                          </button>
                          {isOpen && (
                            <div style={{ paddingLeft: 13, paddingBottom: 8, borderBottom: isLast ? "none" : "1px solid rgba(0,0,0,0.04)" }}>
                              <div style={{ borderLeft: `2px solid ${cfg.color}40`, paddingLeft: 12, display: "flex", flexDirection: "column", gap: 0 }}>
                                {stations.map((name: string, ni: number) => {
                                  const isFirst  = ni === 0;
                                  const isLastSt = ni === stations.length - 1;
                                  const isDisrupted = reroute.disrupted_stops_avoided?.some(
                                    (id: string) => id.toUpperCase().includes(name.substring(0, 4).toUpperCase())
                                  );
                                  return (
                                    <div key={ni} style={{ display: "flex", alignItems: "center", gap: 9, padding: "4px 0" }}>
                                      <div style={{ width: isFirst || isLastSt ? 9 : 6, height: isFirst || isLastSt ? 9 : 6, borderRadius: "50%", flexShrink: 0, background: isDisrupted ? "#ef4444" : (isFirst || isLastSt ? cfg.color : `${cfg.color}60`), border: isFirst || isLastSt ? `2px solid ${cfg.color}` : "none", marginLeft: isFirst || isLastSt ? -1 : 1 }} />
                                      <span style={{ fontSize: 11, fontWeight: isFirst || isLastSt ? 600 : 400, color: isDisrupted ? "#ef4444" : (isFirst || isLastSt ? "#000000" : "#737373") }}>
                                        {name}
                                        {isDisrupted && <span style={{ marginLeft: 5, fontSize: 9, color: "#ef4444" }}>DISRUPTED</span>}
                                      </span>
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </>
              );
            })() : reroute?.error ? (
              <p style={{ fontSize: 12, color: "#ef4444" }}>{reroute.error}</p>
            ) : (
              <p style={{ fontSize: 12, color: "#737373" }}>No route computed — origin/destination not provided.</p>
            )}
          </div>

          {/* Agent 3: RAG Advice */}
          {rag && (
            <div className="card anim-fade-up" style={{ padding: "1.25rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                <span style={{ fontSize: 9, fontFamily: "var(--font-sans)", fontWeight: 700, color: "#22c55e", background: "rgba(34,197,94,0.1)", border: "1px solid rgba(34,197,94,0.2)", padding: "2px 8px", borderRadius: 5 }}>AGENT 3</span>
                <span style={{ fontSize: 12, color: "#5f5f5f", fontWeight: 500 }}>RAG Advice</span>
                <span style={{ marginLeft: "auto", fontSize: 9, color: "#8f8f8f", fontFamily: "var(--font-sans)" }}>{rag.mode} mode</span>
              </div>
              <div className="md-body">
                <ReactMarkdown>{rag.answer}</ReactMarkdown>
              </div>
              {rag.sources?.length > 0 && (
                <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {rag.sources.slice(0, 3).map((src: string) => (
                    <span key={src} style={{ fontSize: 9, color: "#737373", background: "rgba(0,0,0,0.04)", border: "1px solid rgba(0,0,0,0.07)", padding: "2px 7px", borderRadius: 5 }}>
                      {src.replace(/\.pdf|\.txt/gi, "").slice(0, 40)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Meta */}
      <div className="card" style={{ marginTop: 12, padding: "0.7rem 1.1rem", display: "flex", flexWrap: "wrap", gap: "1rem" }}>
        {[["NLP","TF-IDF + LR"],["Routing","GTFS + Dijkstra"],["RAG","gemini-flash-lite"],["Stations","166"]].map(([k,v]) => (
          <span key={k} style={{ fontSize: 10 }}>
            <span style={{ color: "#8f8f8f" }}>{k}: </span>
            <span style={{ color: "#737373" }}>{v}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
