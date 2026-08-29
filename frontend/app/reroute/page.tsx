"use client";
import { useState, useEffect, useRef, Suspense } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import axios from "axios";
import { findRoute, getLineStatus, friendlyError, apiBase, DEFAULT_PREFS, type RoutePreferences } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import StationInput, { useStationOptions } from "@/components/StationInput";
import VoiceInput from "@/components/VoiceInput";
import LiveRegion from "@/components/LiveRegion";

// Leaflet requires browser APIs — must be loaded client-side only
const RouteMap = dynamic(() => import("@/components/RouteMap"), { ssr: false });
const NetworkMap = dynamic(() => import("@/components/NetworkMap"), { ssr: false });

const LINE_CFG: Record<string, { color: string; name: string }> = {
  KJ:  { color: "#ef4444", name: "Kelana Jaya" },
  AG:  { color: "#f97316", name: "Ampang" },
  PH:  { color: "#ec4899", name: "Sri Petaling" },
  KGL: { color: "#22c55e", name: "MRT Kajang" },
  PYL: { color: "#eab308", name: "MRT Putrajaya" },
  MR:  { color: "#84cc16", name: "Monorail" },
  BRT: { color: "#10b981", name: "BRT Sunway" },
  SA:  { color: "#38bdf8", name: "LRT Shah Alam" },
};

const titleCase = (s: string) =>
  s.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());

const minsAgo = (iso: string) => {
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  return m === 0 ? "just now" : `reported ${m} min ago`;
};

const EXAMPLES = [
  { o: "KLCC",         d: "PUTRA HEIGHTS" },
  { o: "MASJID JAMEK", d: "KAJANG" },
  { o: "KL SENTRAL",   d: "GOMBAK" },
];

// ─── Multi-modal alternatives panel ─────────────────────────────────────────

const LINE_COLOR_MAP: Record<string, string> = {
  KJ: "#ef4444", AG: "#f97316", PH: "#ec4899",
  KGL: "#22c55e", PYL: "#eab308", MR: "#84cc16", BRT: "#10b981", SA: "#38bdf8",
};

function AlternativesPanel({ alternatives, disrupted }: { alternatives: any; disrupted: boolean }) {
  const [open, setOpen] = useState(!disrupted ? false : true);
  if (!alternatives) return null;

  const { bridging_buses = [], walkable_nearby = [], ehailing } = alternatives;
  const hasBus  = bridging_buses.length > 0;
  const hasWalk = walkable_nearby.length > 0;

  return (
    <div className="card anim-fade-in" style={{
      marginBottom: 12,
      borderColor: disrupted ? "rgba(239,68,68,0.2)" : "rgba(0,0,0,0.07)",
      background:  disrupted ? "rgba(239,68,68,0.04)" : undefined,
    }}>
      <button onClick={() => setOpen(p => !p)} style={{
        width: "100%", background: "none", border: "none", cursor: "pointer",
        display: "flex", alignItems: "center", gap: 10,
        padding: "1rem 1.25rem", textAlign: "left",
      }}>
        <span style={{ fontSize: 16 }}>{disrupted ? "🚨" : "🚌"}</span>
        <div style={{ flex: 1 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: disrupted ? "#ef4444" : "#000000" }}>
            {disrupted ? "No Rail Route — Alternative Transport Options" : "Alternative Transport Options"}
          </span>
          <span style={{ fontSize: 10, color: "#737373", marginLeft: 8 }}>
            {[hasBus && "bridging bus", hasWalk && "walk", "e-hailing"].filter(Boolean).join(" · ")}
          </span>
        </div>
        <span style={{ fontSize: 11, color: "#8f8f8f" }}>{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div style={{ padding: "0 1.25rem 1.25rem", display: "flex", flexDirection: "column", gap: 12 }}>

          {/* E-hailing — most prominent when disrupted */}
          {ehailing && (
            <div style={{
              background: disrupted ? "rgba(59,130,246,0.1)" : "rgba(0,0,0,0.03)",
              border: `1px solid ${disrupted ? "rgba(59,130,246,0.3)" : "rgba(0,0,0,0.07)"}`,
              borderRadius: 10, padding: "12px 14px",
            }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                <span style={{ fontSize: 22, flexShrink: 0 }}>🚗</span>
                <div style={{ flex: 1 }}>
                  <p style={{ fontSize: 13, fontWeight: 600, color: "#000000", margin: 0 }}>Ride-Hailing Option</p>
                  <p style={{ fontSize: 11, color: "#737373", margin: "3px 0 6px", lineHeight: 1.5 }}>
                    {ehailing.reason}<br />
                    <strong style={{ color: "#000000" }}>Est. fare: {ehailing.fare_estimate}</strong>
                    {ehailing.distance_km > 0 && <span style={{ color: "#8f8f8f" }}> · {ehailing.distance_km} km direct</span>}
                    <br />
                    <span style={{ color: "#8f8f8f" }}>Open Grab (on phone, launches the app) or view the route in Google Maps.</span>
                  </p>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <a href={ehailing.grab_url} target="_blank" rel="noopener noreferrer"
                      style={{ fontSize: 11, fontWeight: 700, color: "#000", background: "#22c55e", padding: "6px 14px", borderRadius: 7, textDecoration: "none", display: "inline-block" }}>
                      Open Grab →
                    </a>
                    {ehailing.maps_url && (
                      <a href={ehailing.maps_url} target="_blank" rel="noopener noreferrer"
                        style={{ fontSize: 11, fontWeight: 600, color: "#000000", background: "rgba(0,0,0,0.06)", border: "1px solid rgba(0,0,0,0.12)", padding: "6px 14px", borderRadius: 7, textDecoration: "none", display: "inline-block" }}>
                        🗺 View in Maps
                      </a>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Bridging buses */}
          {hasBus && (
            <div style={{ background: "rgba(245,158,11,0.07)", border: "1px solid rgba(245,158,11,0.25)", borderRadius: 10, padding: "12px 14px" }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                <span style={{ fontSize: 22, flexShrink: 0 }}>🚌</span>
                <div style={{ flex: 1 }}>
                  <p style={{ fontSize: 13, fontWeight: 600, color: "#f59e0b", margin: 0 }}>RapidKL Bridging Buses</p>
                  {bridging_buses.map((b: any) => (
                    <div key={b.line} style={{ marginTop: 8 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                        <div style={{ width: 3, height: 14, background: LINE_COLOR_MAP[b.line] ?? "#737373", borderRadius: 99, flexShrink: 0 }} />
                        <span style={{ fontSize: 11, color: "#5f5f5f" }}>{b.corridor}</span>
                      </div>
                      <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: 4 }}>
                        {b.routes.map((r: string) => (
                          <span key={r} style={{ fontSize: 10, fontWeight: 700, color: "#f59e0b", background: "rgba(245,158,11,0.12)", border: "1px solid rgba(245,158,11,0.3)", padding: "2px 8px", borderRadius: 5 }}>{r}</span>
                        ))}
                      </div>
                      <p style={{ fontSize: 10, color: "#737373", margin: 0, lineHeight: 1.5 }}>{b.pickup_note}</p>
                    </div>
                  ))}
                  <a href="https://twitter.com/AskRapidKL" target="_blank" rel="noopener noreferrer"
                    style={{ fontSize: 10, color: "#f59e0b", textDecoration: "none", display: "inline-block", marginTop: 8 }}>
                    📢 Check @AskRapidKL on X for live pickup locations →
                  </a>
                </div>
              </div>
            </div>
          )}

          {/* Walkable stations */}
          {hasWalk && (
            <div style={{ background: "rgba(34,197,94,0.06)", border: "1px solid rgba(34,197,94,0.18)", borderRadius: 10, padding: "12px 14px" }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                <span style={{ fontSize: 22, flexShrink: 0 }}>🚶</span>
                <div style={{ flex: 1 }}>
                  <p style={{ fontSize: 13, fontWeight: 600, color: "#22c55e", margin: "0 0 8px" }}>Nearby Stations (Walking Distance)</p>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {walkable_nearby.map((s: any) => (
                      <div key={s.name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <div style={{ width: 3, height: 14, background: LINE_COLOR_MAP[s.line] ?? "#737373", borderRadius: 99, flexShrink: 0 }} />
                        <span style={{ fontSize: 12, color: "#000000", fontWeight: 500 }}>{s.name}</span>
                        <span style={{ fontSize: 10, color: "#737373", marginLeft: "auto" }}>
                          ~{s.walk_minutes} min · {s.distance_m}m
                        </span>
                        <span style={{ fontSize: 9, fontFamily: "var(--font-sans)", color: LINE_COLOR_MAP[s.line] ?? "#737373", background: `${LINE_COLOR_MAP[s.line] ?? "#737373"}18`, border: `1px solid ${LINE_COLOR_MAP[s.line] ?? "#737373"}30`, padding: "1px 6px", borderRadius: 4 }}>{s.line}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          <p style={{ fontSize: 10, color: "#8f8f8f", margin: 0 }}>
            ⚠ Bus routes and fare estimates are approximate. Always verify with the RapidKL app or @AskRapidKL.
          </p>
        </div>
      )}
    </div>
  );
}

const ALL_LINES = [
  { id: "KJ",  name: "Kelana Jaya", color: "#ef4444" },
  { id: "AG",  name: "Ampang",      color: "#f97316" },
  { id: "PH",  name: "Sri Petaling",color: "#ec4899" },
  { id: "KGL", name: "MRT Kajang",  color: "#22c55e" },
  { id: "PYL", name: "MRT Putrajaya",color:"#eab308" },
  { id: "MR",  name: "Monorail",    color: "#84cc16" },
  { id: "BRT", name: "BRT Sunway",  color: "#10b981" },
  { id: "SA",  name: "LRT Shah Alam", color: "#38bdf8" },
];

function ReroutePageInner() {
  const { user, prefs: savedPrefs } = useAuth();
  const searchParams = useSearchParams();
  const avoidParam = searchParams.get("avoid");
  const oParam     = searchParams.get("o");
  const dParam     = searchParams.get("d");
  const autoParam  = searchParams.get("auto") === "1";

  const [origin, setOrigin]       = useState("");
  const [destination, setDest]    = useState("");
  const stationOptions = useStationOptions();
  const [disrupted, setDisrupted] = useState("");
  const [autoAvoided, setAutoAvoided] = useState<
    { name: string; stop_ids: string[]; last_alert_at: string }[]
  >([]);
  const [endpointWarn, setEndpointWarn] = useState<string[]>([]);
  // Single uncorroborated reports: shown, never auto-acted-on (griefing guard)
  const [advisory, setAdvisory] = useState<
    { name: string; stop_ids: string[]; last_alert_at: string; report_count: number }[]
  >([]);
  const [speaking, setSpeaking] = useState(false);
  const canSpeak = typeof window !== "undefined" && "speechSynthesis" in window;
  const [showNetwork, setShowNetwork] = useState(false);
  const [result, setResult]       = useState<any>(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState("");
  const [expanded, setExpanded]   = useState<Record<number, boolean>>({});
  const [showPrefs, setShowPrefs] = useState(false);
  const [prefs, setPrefs]         = useState<RoutePreferences>({ ...DEFAULT_PREFS });
  const [routeIdx, setRouteIdx]   = useState(0);
  // Once the user manually changes any preference this session, saved prefs
  // must NOT re-clobber it. `savedPrefs` gets a fresh object on every Supabase
  // token-refresh / tab-focus (onAuthStateChange), which would otherwise reset
  // the user's in-session toggle (e.g. turning OKU back ON) mid-session.
  const prefsEdited = useRef(false);

  // Seed local prefs from the account — but only until the user edits them.
  useEffect(() => {
    if (prefsEdited.current) return;
    setPrefs({
      priority:            savedPrefs.priority,
      prefer_shelter:      savedPrefs.prefer_shelter,
      avoid_lines:         savedPrefs.avoid_lines,
      require_wheelchair:  savedPrefs.require_wheelchair,
      prefer_less_walking: savedPrefs.prefer_less_walking,
      require_tactile:     savedPrefs.require_tactile,
      prefer_quiet:        savedPrefs.prefer_quiet,
      max_walk_minutes:    savedPrefs.max_walk_minutes,
      prefer_safer_walk:   savedPrefs.prefer_safer_walk,
    });
  }, [savedPrefs]);

  // Auto-prefill from saved Home/Work on first load (only if user hasn't typed anything)
  useEffect(() => {
    if (!origin && savedPrefs.home_station) setOrigin(savedPrefs.home_station);
    if (!destination && savedPrefs.work_station) setDest(savedPrefs.work_station);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedPrefs.home_station, savedPrefs.work_station]);

  // If user landed from Line Status with ?avoid=KJ, auto-add that line to avoid_lines.
  // The dedupe check MUST be inside the functional updater against the CURRENT
  // state — checking the effect's stale `prefs` closure would let a second copy
  // through when the line is already saved (the duplicate-"Ampang" bug).
  useEffect(() => {
    if (!avoidParam) return;
    prefsEdited.current = true;   // deep-linked choice must survive saved-pref re-sync
    setPrefs(p => p.avoid_lines.includes(avoidParam)
      ? p
      : { ...p, avoid_lines: [...p.avoid_lines, avoidParam] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [avoidParam]);

  // If landed with ?o=&d= from another page, fill the form
  useEffect(() => {
    if (oParam) setOrigin(oParam);
    if (dParam) setDest(dParam);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [oParam, dParam]);

  // Auto-fire route search if ?auto=1 and both stations are filled
  useEffect(() => {
    if (autoParam && origin.trim() && destination.trim() && !result && !loading) {
      run();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoParam, origin, destination]);

  // Every manual change marks prefs as user-edited so the saved-prefs sync
  // effect can no longer overwrite the user's choice this session.
  const setPriority = (p: RoutePreferences["priority"]) => {
    prefsEdited.current = true;
    setPrefs(prev => ({ ...prev, priority: p }));
  };

  const toggleShelter = () => {
    prefsEdited.current = true;
    setPrefs(prev => ({ ...prev, prefer_shelter: !prev.prefer_shelter }));
  };

  const toggleWheelchair = () => {
    prefsEdited.current = true;
    setPrefs(prev => ({ ...prev, require_wheelchair: !prev.require_wheelchair }));
  };

  const setMaxWalk = (m: number) => {
    prefsEdited.current = true;
    setPrefs(prev => ({ ...prev, max_walk_minutes: prev.max_walk_minutes === m ? 0 : m }));
  };

  const toggleTactile = () => {
    prefsEdited.current = true;
    setPrefs(prev => ({ ...prev, require_tactile: !prev.require_tactile }));
  };

  const toggleQuiet = () => {
    prefsEdited.current = true;
    setPrefs(prev => ({ ...prev, prefer_quiet: !prev.prefer_quiet }));
  };

  // Fill BOTH station fields from one spoken sentence. The transcript goes to
  // the backend rather than being parsed here: /resolve-stations reuses the
  // whole voice stack — N-best hypothesis selection, the confusion dictionary,
  // and preposition-based direction assignment — so "I want to go to KLCC, I
  // stopped at Kerinchi" fills the fields the right way round rather than in
  // the order the words arrived.
  const [voiceNote, setVoiceNote] = useState("");
  const fillFromSpeech = async (transcript: string) => {
    setVoiceNote("");
    try {
      const { data } = await axios.post(
        `${apiBase()}/api/voice/resolve-stations`, { text: transcript });
      if (data.origin)      setOrigin(data.origin);
      if (data.destination) setDest(data.destination);

      if (data.origin && data.destination) {
        setVoiceNote(`Heard: ${data.origin} → ${data.destination}`);
      } else if (data.origin) {
        setVoiceNote(`Heard origin: ${data.origin} — please add a destination.`);
      } else if (data.suggestion) {
        setVoiceNote(`Did you mean ${data.suggestion}? Please type it to confirm.`);
      } else {
        setVoiceNote(`Could not find a station in: "${transcript}"`);
      }
    } catch {
      setVoiceNote("Could not process that — please type the stations instead.");
    }
  };

  const toggleSaferWalk = () => {
    prefsEdited.current = true;
    setPrefs(prev => ({ ...prev, prefer_safer_walk: !prev.prefer_safer_walk }));
  };

  const toggleAvoidLine = (id: string) => {
    prefsEdited.current = true;
    setPrefs(prev => ({
      ...prev,
      avoid_lines: prev.avoid_lines.includes(id)
        ? prev.avoid_lines.filter(l => l !== id)
        : [...prev.avoid_lines, id],
    }));
  };

  const run = async (oOverride?: string, dOverride?: string, disOverride?: string) => {
    // run is also used as a raw onClick handler, which passes the click
    // event as the first arg — only honour genuine string overrides.
    const o = (typeof oOverride === "string" ? oOverride : origin).trim();
    const d = (typeof dOverride === "string" ? dOverride : destination).trim();
    if (!o || !d) return;
    setLoading(true); setError(""); setResult(null); setExpanded({}); setRouteIdx(0);
    const disSource = typeof disOverride === "string" ? disOverride : disrupted;
    const dis = disSource.split(",").map(s => s.trim()).filter(Boolean);
    // Stations named in live disruption reports (last 30 min) are avoided
    // automatically — unless the station IS the origin/destination (blocking
    // your own endpoint would make the trip impossible; warn instead).
    let auto: { name: string; stop_ids: string[]; last_alert_at: string }[] = [];
    let warn: string[] = [];
    let advis: typeof advisory = [];
    try {
      const ls = await getLineStatus();
      const all = ls?.disrupted_stations ?? [];
      const endpoints = [o.toUpperCase(), d.toUpperCase()];
      auto = all.filter((s: any) => !endpoints.includes(s.name));
      warn = [...all, ...(ls?.advisory_stations ?? [])]
        .filter((s: any) => endpoints.includes(s.name)).map((s: any) => s.name);
      // single uncorroborated reports: inform, don't act (griefing guard)
      advis = (ls?.advisory_stations ?? []).filter((s: any) => !endpoints.includes(s.name));
    } catch { /* status feed unreachable — plan without live avoidance */ }
    setAutoAvoided(auto); setEndpointWarn(warn); setAdvisory(advis);
    const allDis = [...new Set([...dis, ...auto.flatMap(s => s.stop_ids)])];
    const sendPrefs = { ...prefs, avoid_lines: [...new Set(prefs.avoid_lines)] };
    try   { setResult(await findRoute(o.toUpperCase(), d.toUpperCase(), allDis, sendPrefs)); }
    catch (e) { setError(friendlyError(e)); }
    finally { setLoading(false); }
  };

  // Apply a "did you mean" suggestion to the failing field and re-search
  const applySuggestion = (name: string) => {
    if (result?.bad_field === "destination") { setDest(name); run(undefined, name); }
    else { setOrigin(name); run(name, undefined); }
  };

  const toggleExpand = (i: number) =>
    setExpanded(prev => ({ ...prev, [i]: !prev[i] }));

  // ── Read-aloud (Web Speech API) — accessibility for elderly / low-literacy users
  const toggleSpeak = () => {
    if (!canSpeak) return;
    const synth = window.speechSynthesis;
    if (speaking) { synth.cancel(); setSpeaking(false); return; }
    const steps: string[] = active?.instructions ?? [];
    if (!steps.length) return;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(
      steps.map((s, i) => `Step ${i + 1}. ${s}`).join(" ")
    );
    u.rate = 0.92;             // slightly slower than default — easier to follow
    u.onend = () => setSpeaking(false);
    u.onerror = () => setSpeaking(false);
    synth.speak(u);
    setSpeaking(true);
  };

  // Stop speech when the route changes, a new search runs, or the page unmounts
  useEffect(() => {
    if (canSpeak) { window.speechSynthesis.cancel(); setSpeaking(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, routeIdx]);
  useEffect(() => () => { if (canSpeak) window.speechSynthesis.cancel(); }, [canSpeak]);

  // Multi-route: pick the active alternative (old single-route shape still works)
  const routes: any[] = result?.routes ?? (result && !result.error ? [result] : []);
  const active: any = routes[routeIdx] ?? routes[0] ?? {};
  const segments: any[] = active?.segments ?? active?.steps?.map((s: any) => ({
    ...s, stations: [s.from, s.to], n_stops: 1, minutes: null,
  })) ?? [];

  // A route result is a large visual change that announces nothing on its own,
  // so summarise the outcome. Keep it SHORT: a live region is an alert, not a
  // document. Reading every warning paragraph here produced a 500-character
  // utterance that screen readers truncate — the notes are rendered on the
  // page below, where they can be read at the user's own pace. So announce the
  // headline numbers and only COUNT the advisories.
  const announcement = (() => {
    if (loading) return "Finding your route, please wait.";
    if (!result || result.error) return "";
    const advisories = [
      result.safety_note, result.wheelchair_note, result.tactile_note,
      result.shelter_note, result.walking_note,
    ].filter(Boolean).length
      + (endpointWarn.length ? 1 : 0)
      + (autoAvoided.length ? 1 : 0);
    const n = result.interchanges ?? 0;
    const head = `Route found. ${result.origin} to ${result.destination}, `
               + `${result.estimated_minutes} minutes, ${result.total_stops} stops, `
               + `${n === 0 ? "no transfers" : n === 1 ? "1 transfer" : `${n} transfers`}.`;
    return advisories
      ? `${head} ${advisories} advisor${advisories === 1 ? "y" : "ies"} below.`
      : head;
  })();

  return (
    <div className="anim-fade-up" style={{ maxWidth: 960 }}>
      <LiveRegion message={announcement} />
      <LiveRegion message={error || result?.error || ""} politeness="assertive" />

      <p className="section-label" style={{ marginBottom: 8 }}>Rerouting Agent · GTFS + Dijkstra · 187 Stations</p>
      <h1 style={{ fontFamily: "var(--font-sans)", fontSize: 40, fontWeight: 400, letterSpacing: "-0.01em", color: "#000000", marginBottom: 12 }}>
        Journey Recovery Planner
      </h1>
      <p style={{ color: "#737373", fontSize: 13.5, lineHeight: 1.65, marginBottom: "1rem" }}>
        Find the optimal path across 8 rail lines. Stations named in live disruption reports are avoided automatically.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, marginBottom: "1.5rem" }}>
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 6, fontSize: 10, color: "#737373",
          background: "rgba(0,0,0,0.03)", border: "1px solid rgba(0,0,0,0.07)",
          padding: "4px 10px", borderRadius: 7,
        }}>
          <span style={{ color: "#f59e0b" }}>⚠</span>
          Based on static GTFS timetable data — real-time service changes may differ
        </div>
        {/* Hands-free alternative. Voice Help is a separate page, not a mode of
            this form: it also files the report and reads advice aloud, and its
            target users (elderly / low-literacy riders) need a visible entry
            point rather than an icon buried in a dense form. */}
        <Link href="/voice" style={{
          display: "inline-flex", alignItems: "center", gap: 6, fontSize: 10,
          color: "#7c3aed", textDecoration: "none",
          background: "rgba(124,58,237,0.06)", border: "1px solid rgba(124,58,237,0.25)",
          padding: "4px 10px", borderRadius: 7,
        }}>
          🎤 Prefer to speak? Use Voice Help →
        </Link>
      </div>

      {/* Input card */}
      <div className="card" style={{ padding: "1.5rem", marginBottom: 12 }}>
        {/* User prefs banner */}
        {user ? (
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14, padding: "8px 11px", background: "rgba(34,197,94,0.06)", border: "1px solid rgba(34,197,94,0.18)", borderRadius: 8 }}>
            <span style={{ fontSize: 10, color: "#22c55e" }}>✓</span>
            <span style={{ fontSize: 11, color: "#737373", flex: 1 }}>
              Preferences loaded from your profile
              {(savedPrefs.priority !== "fastest" || savedPrefs.prefer_shelter || savedPrefs.avoid_lines.length > 0) && (
                <span style={{ color: "#8f8f8f" }}> · {[
                  savedPrefs.priority !== "fastest" ? savedPrefs.priority.replace("_", " ") : null,
                  savedPrefs.prefer_shelter ? "shelter" : null,
                  savedPrefs.avoid_lines.length > 0 ? `${savedPrefs.avoid_lines.length} avoided` : null,
                ].filter(Boolean).join(", ")}</span>
              )}
            </span>
            <Link href="/settings" style={{ fontSize: 10, color: "#22c55e", textDecoration: "none" }}>Edit →</Link>
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14, padding: "7px 11px", background: "rgba(0,0,0,0.02)", border: "1px solid rgba(0,0,0,0.07)", borderRadius: 8 }}>
            <span style={{ fontSize: 11, color: "#8f8f8f", flex: 1 }}>Sign in to save your route preferences and home/work stations</span>
            <Link href="/login" style={{ fontSize: 10, color: "#5f5f5f", textDecoration: "none", background: "rgba(0,0,0,0.05)", border: "1px solid rgba(0,0,0,0.1)", padding: "3px 9px", borderRadius: 5 }}>Sign In →</Link>
          </div>
        )}

        {/* Quick-fill: prioritize personal Home↔Work, then examples */}
        {user && savedPrefs.home_station && savedPrefs.work_station ? (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
            <button onClick={() => { setOrigin(savedPrefs.home_station); setDest(savedPrefs.work_station); }} className="pill-btn" style={{ fontSize: 11 }}>
              🏠 → 🏢 Home to Work
            </button>
            <button onClick={() => { setOrigin(savedPrefs.work_station); setDest(savedPrefs.home_station); }} className="pill-btn" style={{ fontSize: 11 }}>
              🏢 → 🏠 Work to Home
            </button>
            <button onClick={() => { setOrigin(""); setDest(""); }} className="pill-btn" style={{ fontSize: 11, color: "#737373" }}>
              Clear
            </button>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
            {EXAMPLES.map((ex) => (
              <button key={ex.o} onClick={() => { setOrigin(ex.o); setDest(ex.d); }} className="pill-btn" style={{ fontSize: 11 }}>
                {ex.o} → {ex.d}
              </button>
            ))}
          </div>
        )}

        <div style={{ display: "flex", alignItems: "flex-end", gap: 10, marginBottom: 4 }}>
          <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <StationInput label="Origin" value={origin} onChange={setOrigin}
              placeholder="e.g. KLCC" options={stationOptions} onEnter={run} />
            <StationInput label="Destination" value={destination} onChange={setDest}
              placeholder="e.g. PUTRA HEIGHTS" options={stationOptions} onEnter={run} />
          </div>
          {/* One sentence fills both fields. Fills rather than submits, so a
              mis-heard station can be corrected before searching. */}
          <div style={{ position: "relative", paddingBottom: 2 }}>
            <VoiceInput
              onResult={fillFromSpeech}
              title="Say where you are and where you are going"
            />
          </div>
        </div>
        {voiceNote && (
          <p style={{ fontSize: 11, color: "#737373", marginBottom: 10 }}>{voiceNote}</p>
        )}

        {/* Preferences toggle */}
        <div style={{ marginBottom: 14 }}>
          <button
            onClick={() => setShowPrefs(p => !p)}
            style={{ background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 6, padding: "6px 0", color: showPrefs ? "#000000" : "#737373", fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase" }}
          >
            <span style={{ fontSize: 13 }}>{showPrefs ? "▲" : "▼"}</span>
            Route Preferences
            {(prefs.priority !== "fastest" || prefs.prefer_shelter || prefs.avoid_lines.length > 0) && (
              <span style={{ fontSize: 9, background: "#3b82f6", color: "#fff", padding: "1px 6px", borderRadius: 99, marginLeft: 4 }}>
                {[
                  prefs.priority !== "fastest" ? 1 : 0,
                  prefs.prefer_shelter ? 1 : 0,
                  prefs.avoid_lines.length,
                ].reduce((a, b) => a + b, 0)} active
              </span>
            )}
          </button>

          {showPrefs && (
            <div className="anim-fade-in" style={{ background: "rgba(0,0,0,0.02)", border: "1px solid rgba(0,0,0,0.07)", borderRadius: 10, padding: "1rem", marginTop: 6, display: "flex", flexDirection: "column", gap: 16 }}>

              {/* Priority */}
              <div>
                <p style={{ fontSize: 10, color: "#737373", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>Route Priority</p>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {([
                    { v: "fastest",           label: "⚡ Fastest",          desc: "Minimise travel time" },
                    { v: "fewest_stops",       label: "🔢 Fewest Stops",     desc: "Minimise stop count" },
                    { v: "fewest_transfers",   label: "🔄 Fewest Transfers", desc: "Avoid line changes" },
                  ] as const).map(opt => (
                    <button
                      key={opt.v}
                      onClick={() => setPriority(opt.v)}
                      title={opt.desc}
                      style={{
                        background:  prefs.priority === opt.v ? "rgba(59,130,246,0.15)" : "rgba(0,0,0,0.03)",
                        border:      `1px solid ${prefs.priority === opt.v ? "rgba(59,130,246,0.5)" : "rgba(0,0,0,0.08)"}`,
                        color:       prefs.priority === opt.v ? "#93c5fd" : "#737373",
                        borderRadius: 8, padding: "6px 12px", fontSize: 11, fontWeight: 600, cursor: "pointer",
                        transition: "all 0.15s",
                      }}
                    >{opt.label}</button>
                  ))}
                </div>
                <p style={{ fontSize: 10, color: "#8f8f8f", marginTop: 5 }}>
                  {prefs.priority === "fastest"          && "Uses per-line travel time estimates from GTFS data."}
                  {prefs.priority === "fewest_stops"     && "Counts every station as equal weight — may involve more transfers."}
                  {prefs.priority === "fewest_transfers" && "Heavily penalises line changes — stay on one line as long as possible."}
                </p>
              </div>

              {/* Shelter preference */}
              <div>
                <p style={{ fontSize: 10, color: "#737373", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>Weather / Comfort</p>
                <button
                  onClick={toggleShelter}
                  style={{
                    display: "flex", alignItems: "center", gap: 10, width: "100%",
                    background:  prefs.prefer_shelter ? "rgba(245,158,11,0.08)" : "rgba(0,0,0,0.03)",
                    border:      `1px solid ${prefs.prefer_shelter ? "rgba(245,158,11,0.35)" : "rgba(0,0,0,0.08)"}`,
                    borderRadius: 9, padding: "10px 12px", cursor: "pointer", textAlign: "left",
                    transition: "all 0.15s",
                  }}
                >
                  {/* Toggle pill */}
                  <div style={{
                    width: 34, height: 18, borderRadius: 99, flexShrink: 0,
                    background: prefs.prefer_shelter ? "#f59e0b" : "rgba(0,0,0,0.1)",
                    position: "relative", transition: "background 0.2s",
                  }}>
                    <div style={{
                      position: "absolute", top: 3, left: prefs.prefer_shelter ? 18 : 3,
                      width: 12, height: 12, borderRadius: "50%", background: "#fff",
                      transition: "left 0.2s",
                    }} />
                  </div>
                  <div>
                    <p style={{ fontSize: 12, fontWeight: 600, color: prefs.prefer_shelter ? "#f59e0b" : "#737373", margin: 0 }}>
                      🌧 Prefer Sheltered Route
                    </p>
                    <p style={{ fontSize: 10, color: "#8f8f8f", margin: "2px 0 0" }}>
                      Adds cost to BRT (street-level) and Monorail (open-air) stops — prefers covered LRT/MRT even if slightly slower
                    </p>
                  </div>
                </button>
              </div>

              {/* Accessibility / OKU preference */}
              <div>
                <p style={{ fontSize: 10, color: "#737373", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>Accessibility</p>
                <button
                  onClick={toggleWheelchair}
                  style={{
                    display: "flex", alignItems: "center", gap: 10, width: "100%",
                    background:  prefs.require_wheelchair ? "rgba(59,130,246,0.08)" : "rgba(0,0,0,0.03)",
                    border:      `1px solid ${prefs.require_wheelchair ? "rgba(59,130,246,0.4)" : "rgba(0,0,0,0.08)"}`,
                    borderRadius: 9, padding: "10px 12px", cursor: "pointer", textAlign: "left",
                    transition: "all 0.15s",
                  }}
                >
                  {/* Toggle pill */}
                  <div style={{
                    width: 34, height: 18, borderRadius: 99, flexShrink: 0,
                    background: prefs.require_wheelchair ? "#3b82f6" : "rgba(0,0,0,0.1)",
                    position: "relative", transition: "background 0.2s",
                  }}>
                    <div style={{
                      position: "absolute", top: 3, left: prefs.require_wheelchair ? 18 : 3,
                      width: 12, height: 12, borderRadius: "50%", background: "#fff",
                      transition: "left 0.2s",
                    }} />
                  </div>
                  <div>
                    <p style={{ fontSize: 12, fontWeight: 600, color: prefs.require_wheelchair ? "#3b82f6" : "#737373", margin: 0 }}>
                      ♿ Step-free / OKU accessible
                    </p>
                    <p style={{ fontSize: 10, color: "#8f8f8f", margin: "2px 0 0" }}>
                      Excludes stations without step-free access (lift/ramp). Stations with unverified access are flagged, not assumed
                    </p>
                  </div>
                </button>

                {/* Max walking (bucketed) */}
                <div style={{ marginTop: 8, background: "rgba(0,0,0,0.03)", border: "1px solid rgba(0,0,0,0.08)", borderRadius: 9, padding: "10px 12px" }}>
                  <p style={{ fontSize: 12, fontWeight: 600, color: prefs.max_walk_minutes ? "#0ea5e9" : "#737373", margin: "0 0 2px" }}>
                    🚶 Max walking
                  </p>
                  <p style={{ fontSize: 10, color: "#8f8f8f", margin: "0 0 8px" }}>
                    Prefers routes within your walking limit (approx — mostly transfers). If none fit, shows the least-walking option.
                  </p>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {[{ v: 0, l: "No limit" }, { v: 5, l: "~5 min" }, { v: 10, l: "~10 min" }, { v: 15, l: "~15 min" }].map(opt => {
                      const active = prefs.max_walk_minutes === opt.v;
                      return (
                        <button
                          key={opt.v}
                          onClick={() => setMaxWalk(opt.v)}
                          className="pill-btn"
                          style={{
                            fontSize: 11, fontWeight: active ? 700 : 500,
                            background: active ? "#0ea5e9" : undefined,
                            color: active ? "#fff" : undefined,
                            border: active ? "1px solid #0ea5e9" : undefined,
                          }}
                        >
                          {opt.l}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Blind — tactile guidance alerts */}
                <button
                  onClick={toggleTactile}
                  style={{
                    display: "flex", alignItems: "center", gap: 10, width: "100%", marginTop: 8,
                    background:  prefs.require_tactile ? "rgba(139,92,246,0.08)" : "rgba(0,0,0,0.03)",
                    border:      `1px solid ${prefs.require_tactile ? "rgba(139,92,246,0.4)" : "rgba(0,0,0,0.08)"}`,
                    borderRadius: 9, padding: "10px 12px", cursor: "pointer", textAlign: "left",
                    transition: "all 0.15s",
                  }}
                >
                  <div style={{ width: 34, height: 18, borderRadius: 99, flexShrink: 0, background: prefs.require_tactile ? "#8b5cf6" : "rgba(0,0,0,0.1)", position: "relative", transition: "background 0.2s" }}>
                    <div style={{ position: "absolute", top: 3, left: prefs.require_tactile ? 18 : 3, width: 12, height: 12, borderRadius: "50%", background: "#fff", transition: "left 0.2s" }} />
                  </div>
                  <div>
                    <p style={{ fontSize: 12, fontWeight: 600, color: prefs.require_tactile ? "#8b5cf6" : "#737373", margin: 0 }}>
                      🦯 Blind — tactile guidance alerts
                    </p>
                    <p style={{ fontSize: 10, color: "#8f8f8f", margin: "2px 0 0" }}>
                      Warns about stations whose tactile path may not reach outside. Pair with Voice Help for spoken directions
                    </p>
                  </div>
                </button>

                {/* Prefer a quieter route */}
                <button
                  onClick={toggleQuiet}
                  style={{
                    display: "flex", alignItems: "center", gap: 10, width: "100%", marginTop: 8,
                    background:  prefs.prefer_quiet ? "rgba(5,150,105,0.08)" : "rgba(0,0,0,0.03)",
                    border:      `1px solid ${prefs.prefer_quiet ? "rgba(5,150,105,0.4)" : "rgba(0,0,0,0.08)"}`,
                    borderRadius: 9, padding: "10px 12px", cursor: "pointer", textAlign: "left",
                    transition: "all 0.15s",
                  }}
                >
                  <div style={{ width: 34, height: 18, borderRadius: 99, flexShrink: 0, background: prefs.prefer_quiet ? "#059669" : "rgba(0,0,0,0.1)", position: "relative", transition: "background 0.2s" }}>
                    <div style={{ position: "absolute", top: 3, left: prefs.prefer_quiet ? 18 : 3, width: 12, height: 12, borderRadius: "50%", background: "#fff", transition: "left 0.2s" }} />
                  </div>
                  <div>
                    <p style={{ fontSize: 12, fontWeight: 600, color: prefs.prefer_quiet ? "#059669" : "#737373", margin: 0 }}>
                      💺 Prefer a quieter route
                    </p>
                    <p style={{ fontSize: 10, color: "#8f8f8f", margin: "2px 0 0" }}>
                      Prefers historically less-crowded segments (past ridership averages) — more likely a seat, not guaranteed
                    </p>
                  </div>
                </button>

                {/* Warn about the walking approach at either endpoint */}
                <button
                  onClick={toggleSaferWalk}
                  style={{
                    display: "flex", alignItems: "center", gap: 10, width: "100%", marginTop: 8,
                    background:  prefs.prefer_safer_walk ? "rgba(217,119,6,0.08)" : "rgba(0,0,0,0.03)",
                    border:      `1px solid ${prefs.prefer_safer_walk ? "rgba(217,119,6,0.4)" : "rgba(0,0,0,0.08)"}`,
                    borderRadius: 9, padding: "10px 12px", cursor: "pointer", textAlign: "left",
                    transition: "all 0.15s",
                  }}
                >
                  <div style={{ width: 34, height: 18, borderRadius: 99, flexShrink: 0, background: prefs.prefer_safer_walk ? "#d97706" : "rgba(0,0,0,0.1)", position: "relative", transition: "background 0.2s" }}>
                    <div style={{ position: "absolute", top: 3, left: prefs.prefer_safer_walk ? 18 : 3, width: 12, height: 12, borderRadius: "50%", background: "#fff", transition: "left 0.2s" }} />
                  </div>
                  <div>
                    <p style={{ fontSize: 12, fontWeight: 600, color: prefs.prefer_safer_walk ? "#d97706" : "#737373", margin: 0 }}>
                      🚶 Warn about the walk to/from the station
                    </p>
                    <p style={{ fontSize: 10, color: "#8f8f8f", margin: "2px 0 0" }}>
                      Flags low-scoring walking approaches (lighting, passers-by, crossings, bushes, traffic barriers). Street View estimate, not verified crime data — route unchanged
                    </p>
                  </div>
                </button>
              </div>

              {/* Avoid lines */}
              <div>
                <p style={{ fontSize: 10, color: "#737373", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>Avoid Lines</p>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {ALL_LINES.map(line => {
                    const avoided = prefs.avoid_lines.includes(line.id);
                    return (
                      <button
                        key={line.id}
                        onClick={() => toggleAvoidLine(line.id)}
                        style={{
                          display: "flex", alignItems: "center", gap: 5,
                          background:  avoided ? "rgba(239,68,68,0.1)"  : `${line.color}10`,
                          border:      `1px solid ${avoided ? "rgba(239,68,68,0.35)" : `${line.color}30`}`,
                          color:       avoided ? "#ef4444" : line.color,
                          borderRadius: 7, padding: "5px 10px", fontSize: 10, fontWeight: 600, cursor: "pointer",
                          transition: "all 0.15s",
                          textDecoration: avoided ? "line-through" : "none",
                        }}
                      >
                        {avoided && <span style={{ fontSize: 10 }}>✕ </span>}
                        {line.name}
                      </button>
                    );
                  })}
                </div>
                {prefs.avoid_lines.length > 0 && (
                  <p style={{ fontSize: 10, color: "#ef4444", marginTop: 6 }}>
                    {prefs.avoid_lines.length} line{prefs.avoid_lines.length > 1 ? "s" : ""} excluded — route may be longer or unavailable.
                  </p>
                )}
              </div>

              {/* Advanced: known disrupted stops (dev / power-user) */}
              <div>
                <p style={{ fontSize: 10, color: "#737373", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>
                  Skip Specific Stops <span style={{ color: "#8f8f8f", textTransform: "none" }}>(advanced)</span>
                </p>
                <input className="input" style={{ borderColor: "rgba(239,68,68,0.15)" }}
                  placeholder="e.g. Kampung Baru, KJ16" value={disrupted}
                  onChange={e => setDisrupted(e.target.value)} />
                <p style={{ fontSize: 10, color: "#8f8f8f", marginTop: 5 }}>
                  Comma-separated station names or stop IDs to exclude from routing.
                </p>
              </div>

            </div>
          )}
        </div>

        <button className="btn-primary" onClick={() => run()} disabled={loading || !origin.trim() || !destination.trim()}>
          {loading
            ? <><span className="anim-spin" style={{ width: 13, height: 13, border: "2px solid rgba(255,255,255,0.4)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block" }} /> Finding…</>
            : "Find Route →"}
        </button>

        {error && (
          <div className="anim-fade-in" style={{ marginTop: 14, background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 10, padding: "10px 14px", display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ color: "#ef4444", fontSize: 12, flex: 1 }}>{error}</span>
            <button className="pill-btn" onClick={() => run()} style={{ fontSize: 11, flexShrink: 0 }}>↻ Retry</button>
          </div>
        )}
      </div>

      {/* Full network map — helps unfamiliar / tourist riders see every line
          and station before planning. Lazy: only loads when opened. */}
      <div className="card" style={{ padding: "1rem 1.25rem", marginBottom: 12 }}>
        <button
          onClick={() => setShowNetwork(v => !v)}
          style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", background: "none", border: "none", cursor: "pointer", padding: 0 }}
        >
          <span style={{ fontSize: 13, fontWeight: 600, color: "#2e2e2e" }}>
            🗺 View full network map
            <span style={{ fontSize: 11, fontWeight: 400, color: "#8f8f8f" }}> · all 187 stations, 8 lines</span>
          </span>
          <span style={{ fontSize: 13, color: "#8f8f8f" }}>{showNetwork ? "▲" : "▼"}</span>
        </button>
        {showNetwork && (
          <div style={{ marginTop: 14 }}>
            <NetworkMap />
          </div>
        )}
      </div>

      {/* Result */}
      {loading && !result && (
        <div className="card anim-fade-in" style={{ padding: "1.5rem", marginBottom: 12 }}>
          <div style={{ height: 11, width: 120, background: "rgba(0,0,0,0.06)", borderRadius: 5, marginBottom: 16 }} />
          <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
            {[110, 80, 90].map((w, i) => (
              <div key={i} style={{ height: 24, width: w, background: "rgba(0,0,0,0.05)", borderRadius: 99 }} />
            ))}
          </div>
          <div style={{ height: 220, background: "rgba(0,0,0,0.04)", borderRadius: 12, marginBottom: 16 }} />
          {[0, 1, 2].map(i => (
            <div key={i} style={{ height: 13, width: `${80 - i * 18}%`, background: "rgba(0,0,0,0.05)", borderRadius: 5, marginBottom: 10 }} />
          ))}
        </div>
      )}

      {result && !result.error && (
        <div className="card anim-fade-up" style={{ padding: "1.5rem" }}>
          <p className="section-label" style={{ marginBottom: 14 }}>Intelligent Route Optimization using GTFS & Dijkstra</p>

          {routes.length > 1 && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
              {routes.map((r: any, i: number) => (
                <button key={i} className="pill-btn"
                  onClick={() => { setRouteIdx(i); setExpanded({}); }}
                  style={{
                    fontSize: 12,
                    borderColor: i === routeIdx ? "#000000" : undefined,
                    color:       i === routeIdx ? "#000000" : undefined,
                    fontWeight:  i === routeIdx ? 600 : 500,
                  }}>
                  {i === 0 ? "⚡ Best" : r.through_disruption ? "⚠ Via disruption" : r.slow_option ? "🐢 Slower" : `Alternate ${i}`} · {r.estimated_minutes} min · {r.interchanges} transfer{r.interchanges === 1 ? "" : "s"}{r.walk_minutes != null ? ` · 🚶 ~${r.walk_minutes} min walk` : ""}
                </button>
              ))}
            </div>
          )}

          {active.slow_option && (
            <p style={{ fontSize: 12, color: "#5f5f5f", background: "rgba(0,0,0,0.03)", border: "1px solid rgba(0,0,0,0.08)", borderRadius: 8, padding: "8px 12px", marginBottom: 12 }}>
              🐢 This route is {active.estimated_minutes - routes[0].estimated_minutes} min slower than the best option — shown as a backup in case the faster lines are crowded or disrupted.
            </p>
          )}

          {active.through_disruption && (
            <p style={{ fontSize: 12, color: "#b91c1c", background: "rgba(239,68,68,0.06)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: 8, padding: "8px 12px", marginBottom: 12 }}>
              ⚠ This is the normal route — it passes through{" "}
              {(result.disrupted_points ?? []).map((dp: any) => titleCase(dp.name)).join(", ") || "a disrupted station"},
              which has a reported disruption. Expect delays or closure there; the ⚡ Best route avoids it.
            </p>
          )}

          {result.query_corrected && !result.place_notes?.length && (
            <p style={{ fontSize: 12, color: "#b45309", background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.25)", borderRadius: 8, padding: "8px 12px", marginBottom: 12 }}>
              Showing route for <strong>{result.origin} → {result.destination}</strong> (we auto-corrected your search).
            </p>
          )}

          {result.place_notes?.map((n: any) => (
            <p key={n.field} style={{ fontSize: 12, color: "#1d4ed8", background: "rgba(59,130,246,0.07)", border: "1px solid rgba(59,130,246,0.2)", borderRadius: 8, padding: "8px 12px", marginBottom: 12 }}>
              📍 “{n.query}” isn’t a station — using the nearest one: <strong>{n.station}</strong> ({n.distance_m} m away, ~{n.walk_minutes} min walk)
              {n.lat && n.lon && (
                <>
                  {" · "}
                  <a
                    href={`https://www.google.com/maps/dir/?api=1&origin=${n.lat},${n.lon}&destination=${encodeURIComponent(n.station + " station")}&travelmode=walking`}
                    target="_blank" rel="noopener noreferrer"
                    style={{ color: "#1d4ed8", fontWeight: 600 }}
                  >
                    Walking directions ↗
                  </a>
                </>
              )}
            </p>
          ))}

          {/* Advisories. Grouped in a labelled region so a screen-reader user can
              jump straight here (NVDA: D for landmarks) after the live region
              tells them how many there are — the announcement stays short and
              the detail stays readable at the user's own pace. */}
          <section aria-label="Route advisories">

          {/* Walking reminder — route is walk-heavy */}
          {result.walking_note && (
            <p style={{ fontSize: 12.5, color: "#b45309", background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.3)", borderRadius: 8, padding: "10px 12px", marginBottom: 12, lineHeight: 1.5 }}>
              🚶 {result.walking_note.message}
            </p>
          )}

          {/* Accessibility — stations on the route without verified step-free access */}
          {result.wheelchair_note && (
            <p style={{ fontSize: 12.5, color: "#1d4ed8", background: "rgba(59,130,246,0.07)", border: "1px solid rgba(59,130,246,0.25)", borderRadius: 8, padding: "10px 12px", marginBottom: 12, lineHeight: 1.5 }}>
              ♿ {result.wheelchair_note.message}
            </p>
          )}

          {/* Blind — stations whose tactile path may not reach outside */}
          {result.tactile_note && (
            <p style={{ fontSize: 12.5, color: "#6d28d9", background: "rgba(139,92,246,0.07)", border: "1px solid rgba(139,92,246,0.25)", borderRadius: 8, padding: "10px 12px", marginBottom: 12, lineHeight: 1.5 }}>
              🦯 {result.tactile_note.message}
            </p>
          )}

          {/* Shelter — an open-air interchange walk remains on the route */}
          {result.shelter_note && (
            <p style={{ fontSize: 12.5, color: "#b45309", background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.3)", borderRadius: 8, padding: "10px 12px", marginBottom: 12, lineHeight: 1.5 }}>
              🌧 {result.shelter_note.message}
            </p>
          )}

          {/* Walk safety — low-scoring walking approach at an endpoint. Amber for
              a medium score, red for bad. Advisory only; the route is unchanged. */}
          {result.safety_note && (
            <p style={{
              fontSize: 12.5,
              color:      result.safety_note.level === "bad" ? "#b91c1c" : "#b45309",
              background: result.safety_note.level === "bad" ? "rgba(239,68,68,0.07)" : "rgba(245,158,11,0.08)",
              border:     `1px solid ${result.safety_note.level === "bad" ? "rgba(239,68,68,0.3)" : "rgba(245,158,11,0.3)"}`,
              borderRadius: 8, padding: "10px 12px", marginBottom: 12, lineHeight: 1.5,
            }}>
              🚶 {result.safety_note.message}
            </p>
          )}

          {/* Live disruption avoidance — stations named in recent reports */}
          {autoAvoided.length > 0 && (
            <div className="anim-fade-in" style={{
              background: "rgba(239,68,68,0.05)", border: "1px solid rgba(239,68,68,0.25)",
              borderRadius: 12, padding: "12px 16px", marginBottom: 12,
              display: "flex", alignItems: "center", gap: 12,
            }}>
              <span style={{ fontSize: 16 }}>🚧</span>
              <span style={{ flex: 1, fontSize: 12.5, color: "#5f5f5f", lineHeight: 1.5 }}>
                Routing around{" "}
                {autoAvoided.map((s, i) => (
                  <span key={s.name}>
                    {i > 0 && ", "}
                    <strong style={{ color: "#ef4444" }}>{titleCase(s.name)}</strong>
                    {" "}({minsAgo(s.last_alert_at)})
                  </span>
                ))}
                {" "}— reported disrupted in the last 30 minutes.
              </span>
            </div>
          )}
          {/* Uncorroborated single reports — visible but never auto-acted-on */}
          {advisory.length > 0 && (
            <div className="anim-fade-in" style={{
              background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.3)",
              borderRadius: 12, padding: "12px 16px", marginBottom: 12,
              display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap",
            }}>
              <span style={{ fontSize: 16 }}>👀</span>
              <span style={{ flex: 1, minWidth: 220, fontSize: 12.5, color: "#5f5f5f", lineHeight: 1.5 }}>
                {advisory.map((s, i) => (
                  <span key={s.name}>
                    {i > 0 && ", "}
                    <strong>{titleCase(s.name)}</strong> ({minsAgo(s.last_alert_at)})
                  </span>
                ))}
                {" "}— <strong>1 unverified report</strong>. Routes unchanged until a
                second report confirms it.
              </span>
              <button
                className="pill-btn"
                style={{ fontSize: 11 }}
                onClick={() => {
                  const merged = [
                    ...disrupted.split(",").map(x => x.trim()).filter(Boolean),
                    ...advisory.flatMap(s => s.stop_ids),
                  ];
                  const next = [...new Set(merged)].join(", ");
                  setDisrupted(next);
                  run(undefined, undefined, next);
                }}
              >
                Avoid anyway
              </button>
            </div>
          )}

          {result.disrupted_unresolved?.length > 0 && (
            <p style={{ fontSize: 12, color: "#b45309", background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.3)", borderRadius: 8, padding: "8px 12px", marginBottom: 12 }}>
              ⚠ Not recognised as a station or stop ID:{" "}
              <strong>{result.disrupted_unresolved.join(", ")}</strong> — NOT excluded
              from this route. Check the spelling, or use an exact stop ID (e.g. KG15).
            </p>
          )}

          {endpointWarn.length > 0 && (
            <div className="anim-fade-in" style={{
              background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.3)",
              borderRadius: 12, padding: "12px 16px", marginBottom: 12,
              display: "flex", alignItems: "center", gap: 12,
            }}>
              <span style={{ fontSize: 16 }}>⚠️</span>
              <span style={{ flex: 1, fontSize: 12.5, color: "#5f5f5f", lineHeight: 1.5 }}>
                Heads up: {endpointWarn.map(titleCase).join(", ")}{" "}
                {endpointWarn.length > 1 ? "have" : "has"} a disruption reported in the
                last 30 minutes — expect delays at your {" "}
                {endpointWarn.length > 1 ? "stations" : "station"}.
              </span>
            </div>
          )}

          </section>

          {/* Applied preferences notice */}
          {result.preferences_applied && (
            result.preferences_applied.priority !== "fastest" ||
            result.preferences_applied.prefer_shelter ||
            result.preferences_applied.avoid_lines?.length > 0
          ) && (
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: 10 }}>
              <span style={{ fontSize: 9, color: "#737373", alignSelf: "center" }}>Preferences:</span>
              {result.preferences_applied.priority !== "fastest" && (
                <span style={{ fontSize: 10, color: "#93c5fd", background: "rgba(59,130,246,0.1)", border: "1px solid rgba(59,130,246,0.25)", padding: "2px 8px", borderRadius: 99 }}>
                  {result.preferences_applied.priority === "fewest_stops" ? "🔢 Fewest stops" : "🔄 Fewest transfers"}
                </span>
              )}
              {result.preferences_applied.prefer_shelter && (
                <span style={{ fontSize: 10, color: "#f59e0b", background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.25)", padding: "2px 8px", borderRadius: 99 }}>🌧 Shelter preferred</span>
              )}
              {[...new Set<string>(result.preferences_applied.avoid_lines ?? [])].map((l: string) => (
                <span key={l} style={{ fontSize: 10, color: "#ef4444", background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.25)", padding: "2px 8px", borderRadius: 99 }}>✕ {LINE_CFG[l]?.name ?? l}</span>
              ))}
            </div>
          )}

          {/* Summary badges */}
          <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginBottom: 22 }}>
            {[
              { label: `${result.origin} → ${result.destination}`, color: "#000000", bg: "rgba(0,0,0,0.05)", bd: "rgba(0,0,0,0.1)" },
              { label: `${active.total_stops} stops`,              color: "#3b82f6", bg: "rgba(59,130,246,0.1)",   bd: "rgba(59,130,246,0.25)" },
              { label: `~${active.estimated_minutes} min`,         color: "#22c55e", bg: "rgba(34,197,94,0.1)",    bd: "rgba(34,197,94,0.25)" },
              ...(active.interchanges > 0
                ? [{ label: `${active.interchanges} transfer${active.interchanges > 1 ? "s" : ""}`, color: "#f59e0b", bg: "rgba(245,158,11,0.1)", bd: "rgba(245,158,11,0.25)" }]
                : [{ label: "Direct", color: "#22c55e", bg: "rgba(34,197,94,0.08)", bd: "rgba(34,197,94,0.2)" }]),
              ...(active.walk_minutes != null
                ? [{ label: `🚶 ~${active.walk_minutes} min walk`, color: "#0ea5e9", bg: "rgba(14,165,233,0.1)", bd: "rgba(14,165,233,0.25)" }]
                : []),
              ...(result.disrupted_stops_avoided?.length > 0
                ? [{ label: `${result.disrupted_stops_avoided.length} avoided`, color: "#ef4444", bg: "rgba(239,68,68,0.1)", bd: "rgba(239,68,68,0.25)" }]
                : []),
            ].map(b => (
              <span key={b.label} style={{ fontSize: 11, fontWeight: 600, color: b.color, background: b.bg, border: `1px solid ${b.bd}`, padding: "4px 12px", borderRadius: 99 }}>{b.label}</span>
            ))}
          </div>

          {/* Preference feedback — every toggle gets an honest response */}
          {result.preference_note && (() => {
            const reason = result.preference_note.reason;
            const tone = reason === "faster_without_preferences"
              ? { bg: "rgba(245,158,11,0.07)", bd: "rgba(245,158,11,0.3)", icon: "💡" }
              : reason === "rerouted_for_preferences"
              ? { bg: "rgba(59,130,246,0.06)", bd: "rgba(59,130,246,0.25)", icon: "🔀" }
              : { bg: "rgba(34,197,94,0.06)", bd: "rgba(34,197,94,0.25)", icon: "✓" };
            return (
              <div className="anim-fade-in" style={{
                background: tone.bg, border: `1px solid ${tone.bd}`,
                borderRadius: 12, padding: "14px 16px", marginBottom: 18,
                display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap",
              }}>
                <span style={{ fontSize: 18 }}>{tone.icon}</span>
                <span style={{ flex: 1, fontSize: 13, color: "#5f5f5f", lineHeight: 1.5, minWidth: 220 }}>
                  {result.preference_note.message}
                </span>
                {result.relaxed_route && (
                  <button
                    className="pill-btn"
                    style={{ fontSize: 12, borderColor: "#f59e0b", color: "#b45309" }}
                    onClick={() => { setRouteIdx(0); setResult({ ...result.relaxed_route, preference_note: null, relaxed_route: null }); }}
                  >
                    Use faster route →
                  </button>
                )}
              </div>
            );
          })()}

          {/* Plain-language journey steps */}
          {active.instructions?.length > 0 && (
            <div style={{ marginBottom: 22 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                <p className="section-label" style={{ margin: 0 }}>How to get there</p>
                {canSpeak && (
                  <button
                    onClick={toggleSpeak}
                    aria-label={speaking ? "Stop reading directions aloud" : "Read directions aloud"}
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 7,
                      minHeight: 40, padding: "8px 16px", borderRadius: 99,
                      fontSize: 13, fontWeight: 600, cursor: "pointer",
                      background: speaking ? "#000000" : "rgba(0,0,0,0.04)",
                      color:      speaking ? "#ffffff" : "#2e2e2e",
                      border: "1px solid rgba(0,0,0,0.12)",
                    }}
                  >
                    {speaking ? "⏹ Stop" : "🔊 Read aloud"}
                  </button>
                )}
              </div>
              <ol style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 10 }}>
                {active.instructions.map((step: string, i: number) => (
                  <li key={i} style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                    <span style={{
                      width: 24, height: 24, borderRadius: "50%", flexShrink: 0,
                      background: "#000000", color: "#ffffff",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 12, fontWeight: 500,
                    }}>{i + 1}</span>
                    <span style={{ fontSize: 15, color: "#2e2e2e", lineHeight: 1.55, paddingTop: 2 }}>{step}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Map */}
          {segments.some((s: any) => s.station_points?.length >= 2) && (() => {
            const allPts = segments.flatMap((s: any) => s.station_points ?? []);
            const first = allPts[0];
            const last  = allPts[allPts.length - 1];
            // Use station names (more reliable than raw lat/lon for transit search in Google Maps)
            const originName = first ? `${first.name} LRT Station, Kuala Lumpur` : "";
            const destName   = last  ? `${last.name} LRT Station, Kuala Lumpur`  : "";
            const gmapsUrl = first && last
              ? `https://www.google.com/maps/dir/?api=1`
                + `&origin=${encodeURIComponent(originName)}`
                + `&destination=${encodeURIComponent(destName)}`
                + `&travelmode=transit`
              : null;

            return (
              <div style={{ position: "relative", marginBottom: 22 }}>
                <div style={{ height: 460, borderRadius: 12, overflow: "hidden", border: "1px solid rgba(0,0,0,0.07)" }}>
                  <RouteMap
                    segments={segments}
                    disrupted_avoided={result.disrupted_stops_avoided ?? []}
                    disrupted_points={result.disrupted_points ?? []}
                    disrupted_route={
                      active.through_disruption ? []
                        : routes.find((rt: any) => rt.through_disruption)?.segments ?? []
                    }
                    places={(result.place_notes ?? []).filter((n: any) => n.lat && n.lon)}
                  />
                </div>
                {gmapsUrl && (
                  <a
                    href={gmapsUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      position: "absolute", top: 10, right: 10, zIndex: 500,
                      display: "inline-flex", alignItems: "center", gap: 6,
                      background: "rgba(255,255,255,0.92)",
                      border: "1px solid rgba(0,0,0,0.15)",
                      color: "#000000", textDecoration: "none",
                      fontSize: 11, fontWeight: 600,
                      padding: "7px 12px", borderRadius: 8,
                      backdropFilter: "blur(8px)",
                    }}
                  >
                    🗺 Open in Google Maps ↗
                  </a>
                )}
              </div>
            );
          })()}

          {/* Journey segments */}
          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {segments.map((seg: any, si: number) => {
              const cfg      = LINE_CFG[seg.line] ?? { color: "#737373", name: seg.line };
              const isOpen   = !!expanded[si];
              const stations: string[] = seg.stations ?? [seg.from, seg.to];
              const isLast   = si === segments.length - 1;

              return (
                <div key={si}>
                  {/* Transfer badge between segments */}
                  {si > 0 && (
                    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0 8px 20px" }}>
                      <div style={{ width: 2, background: "rgba(0,0,0,0.06)", alignSelf: "stretch" }} />
                      <span style={{
                        fontSize: 10, fontWeight: 600, color: "#f59e0b",
                        background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.25)",
                        padding: "2px 10px", borderRadius: 99,
                      }}>⇄ Transfer at {seg.from}</span>
                    </div>
                  )}

                  {/* Segment header — clickable to expand */}
                  <button
                    onClick={() => toggleExpand(si)}
                    style={{
                      width: "100%", background: "none", border: "none", cursor: "pointer",
                      display: "flex", alignItems: "center", gap: 12,
                      padding: "10px 0", textAlign: "left",
                      borderBottom: isOpen ? "none" : (isLast ? "none" : "1px solid rgba(0,0,0,0.04)"),
                    }}
                  >
                    {/* Line colour bar */}
                    <div style={{ width: 3, alignSelf: "stretch", background: cfg.color, borderRadius: 99, flexShrink: 0 }} />

                    <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 3 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{
                          fontSize: 9, fontFamily: "var(--font-sans)", fontWeight: 700,
                          color: cfg.color, background: `${cfg.color}18`, border: `1px solid ${cfg.color}30`,
                          padding: "2px 8px", borderRadius: 5, flexShrink: 0,
                        }}>{cfg.name}</span>
                        <span style={{ fontSize: 12, color: "#000000", fontWeight: 600 }}>{seg.from}</span>
                        <span style={{ color: "#8f8f8f", fontSize: 11 }}>→</span>
                        <span style={{ fontSize: 12, color: "#000000", fontWeight: 600 }}>{seg.to}</span>
                      </div>
                      <span style={{ fontSize: 10, color: "#737373", paddingLeft: 2 }}>
                        {seg.n_stops} stop{seg.n_stops !== 1 ? "s" : ""}
                        {seg.minutes ? ` · ~${seg.minutes} min` : ""}
                        {" · "}
                        <span style={{ color: cfg.color }}>
                          {isOpen ? "▲ hide stations" : "▼ show all stations"}
                        </span>
                      </span>
                    </div>
                  </button>

                  {/* Station list — expandable */}
                  {isOpen && (
                    <div style={{
                      paddingLeft: 15, paddingBottom: 10,
                      borderBottom: isLast ? "none" : "1px solid rgba(0,0,0,0.04)",
                    }}>
                      <div style={{ borderLeft: `2px solid ${cfg.color}40`, paddingLeft: 14, display: "flex", flexDirection: "column", gap: 0 }}>
                        {stations.map((name: string, ni: number) => {
                          const isFirst = ni === 0;
                          const isLastSt = ni === stations.length - 1;
                          const isDisrupted = result.disrupted_stops_avoided?.some(
                            (id: string) => id.toUpperCase().includes(name.substring(0, 4).toUpperCase())
                          );
                          return (
                            <div key={ni} style={{ display: "flex", alignItems: "center", gap: 10, padding: "5px 0" }}>
                              {/* Dot */}
                              <div style={{
                                width: isFirst || isLastSt ? 10 : 7,
                                height: isFirst || isLastSt ? 10 : 7,
                                borderRadius: "50%", flexShrink: 0,
                                background: isDisrupted ? "#ef4444" : (isFirst || isLastSt ? cfg.color : `${cfg.color}60`),
                                border: isFirst || isLastSt ? `2px solid ${cfg.color}` : "none",
                                marginLeft: isFirst || isLastSt ? -1 : 1,
                              }} />
                              <span style={{
                                fontSize: 11.5,
                                fontWeight: isFirst || isLastSt ? 600 : 400,
                                color: isDisrupted ? "#ef4444" : (isFirst || isLastSt ? "#000000" : "#737373"),
                              }}>
                                {name}
                                {isDisrupted && <span style={{ marginLeft: 6, fontSize: 9, color: "#ef4444" }}>DISRUPTED</span>}
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
        </div>
      )}

      {result?.error && (
        <div className="anim-fade-in" style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", color: "#ef4444", fontSize: 13, padding: "12px 16px", borderRadius: 12, marginBottom: 12 }}>
          🚫 {result.error}
          {result.suggestions?.length > 0 && (
            <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={{ fontSize: 12, color: "#5f5f5f" }}>Did you mean:</span>
              {result.suggestions.map((name: string) => (
                <button key={name} className="pill-btn" style={{ fontSize: 12 }}
                  onClick={() => applySuggestion(name)}>
                  {name}
                </button>
              ))}
            </div>
          )}
          {result.relaxed_route && (
            <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <span style={{ fontSize: 12, color: "#5f5f5f" }}>
                A route exists without your preferences (~{result.relaxed_route.estimated_minutes} min).
              </span>
              <button
                className="pill-btn"
                style={{ fontSize: 12 }}
                onClick={() => { setRouteIdx(0); setResult({ ...result.relaxed_route, preference_note: null, relaxed_route: null }); }}
              >
                Show that route →
              </button>
            </div>
          )}
        </div>
      )}

      {/* Multi-modal alternatives — shown on both success and no-route-found */}
      {result && <AlternativesPanel alternatives={result.alternatives} disrupted={!!(result.error)} />}

      {/* Meta */}
      <div className="card" style={{ marginTop: 12, padding: "0.7rem 1.1rem", display: "flex", flexWrap: "wrap", gap: "1rem" }}>
        {[["Algorithm","Dijkstra"],["Graph","GTFS stops + edges"],["Stations","187"],["Lines","8 rail lines"]].map(([k,v]) => (
          <span key={k} style={{ fontSize: 10 }}>
            <span style={{ color: "#8f8f8f" }}>{k}: </span>
            <span style={{ color: "#737373" }}>{v}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// useSearchParams() requires a Suspense boundary for the production build
// (static prerender bails out to client rendering without it).
export default function ReroutePage() {
  return (
    <Suspense fallback={<div className="anim-fade-up" style={{ maxWidth: 640, minHeight: 400 }} />}>
      <ReroutePageInner />
    </Suspense>
  );
}
