"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth, type UserPreferences, DEFAULT_USER_PREFS } from "@/lib/auth";
import StationInput, { useStationOptions } from "@/components/StationInput";

const ALL_LINES = [
  { id: "KJ",  name: "Kelana Jaya",  color: "#ef4444", note: "LRT · elevated/covered" },
  { id: "AG",  name: "Ampang",       color: "#f97316", note: "LRT · elevated/covered" },
  { id: "PH",  name: "Sri Petaling", color: "#ec4899", note: "LRT · elevated/covered" },
  { id: "KGL", name: "MRT Kajang",   color: "#22c55e", note: "MRT · underground/elevated" },
  { id: "PYL", name: "MRT Putrajaya",color: "#eab308", note: "MRT · underground/elevated" },
  { id: "MR",  name: "Monorail",     color: "#84cc16", note: "Monorail · open-air" },
  { id: "BRT", name: "BRT Sunway",   color: "#10b981", note: "BRT · street-level" },
  { id: "SA",  name: "LRT Shah Alam", color: "#38bdf8", note: "LRT · elevated/covered" },
];

export default function SettingsPage() {
  const { user, prefs, savePreferences, signOut, loading } = useAuth();
  const router = useRouter();

  const [local,   setLocal]   = useState<UserPreferences>({ ...DEFAULT_USER_PREFS });
  const stationOptions = useStationOptions();
  const [saving,  setSaving]  = useState(false);
  const [saved,   setSaved]   = useState(false);
  const [error,   setError]   = useState("");

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  useEffect(() => {
    setLocal({ ...prefs });
  }, [prefs]);

  if (loading || !user) return null;

  const setPriority = (p: UserPreferences["priority"]) =>
    setLocal(prev => ({ ...prev, priority: p }));

  const toggleShelter = () =>
    setLocal(prev => ({ ...prev, prefer_shelter: !prev.prefer_shelter }));

  const toggleWheelchair = () =>
    setLocal(prev => ({ ...prev, require_wheelchair: !prev.require_wheelchair }));

  const setMaxWalk = (m: number) =>
    setLocal(prev => ({ ...prev, max_walk_minutes: prev.max_walk_minutes === m ? 0 : m }));

  const toggleTactile = () =>
    setLocal(prev => ({ ...prev, require_tactile: !prev.require_tactile }));

  const toggleQuiet = () =>
    setLocal(prev => ({ ...prev, prefer_quiet: !prev.prefer_quiet }));

  const toggleSaferWalk = () =>
    setLocal(prev => ({ ...prev, prefer_safer_walk: !prev.prefer_safer_walk }));

  const toggleLine = (id: string) =>
    setLocal(prev => ({
      ...prev,
      avoid_lines: prev.avoid_lines.includes(id)
        ? prev.avoid_lines.filter(l => l !== id)
        : [...prev.avoid_lines, id],
    }));

  const save = async () => {
    setSaving(true); setError(""); setSaved(false);
    const err = await savePreferences(local);
    setSaving(false);
    if (err) setError(err);
    else { setSaved(true); setTimeout(() => setSaved(false), 2500); }
  };

  const reset = () => setLocal({ ...DEFAULT_USER_PREFS });

  return (
    <div className="anim-fade-up" style={{ maxWidth: 960 }}>

      <p className="section-label" style={{ marginBottom: 8 }}>Profile</p>
      <h1 style={{ fontFamily: "var(--font-sans)", fontSize: 40, fontWeight: 400, letterSpacing: "-0.01em", color: "#000000", marginBottom: 12 }}>
        Personalisation Preferences (Hyperpersonalization)
      </h1>
      <p style={{ color: "#737373", fontSize: 13, marginBottom: "2rem" }}>
        These settings are saved to your account and automatically applied every time you search for a route.
      </p>

      {/* Account */}
      <div className="card" style={{ padding: "1.1rem 1.25rem", marginBottom: 12, display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ width: 36, height: 36, borderRadius: "50%", background: "#22c55e", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--font-sans)", fontWeight: 900, fontSize: 13, color: "#000", flexShrink: 0 }}>
          {user.email?.slice(0, 2).toUpperCase()}
        </div>
        <div style={{ flex: 1 }}>
          <p style={{ fontSize: 13, color: "#000000", fontWeight: 500, margin: 0 }}>{user.email}</p>
          <p style={{ fontSize: 10, color: "#8f8f8f", margin: "2px 0 0" }}>Signed in · preferences sync automatically</p>
        </div>
        <button onClick={() => signOut().then(() => router.push("/"))}
          style={{ background: "none", border: "1px solid rgba(0,0,0,0.08)", color: "#737373", fontSize: 10, padding: "5px 10px", borderRadius: 6, cursor: "pointer" }}>
          Sign Out
        </button>
      </div>

      {/* Quick Routes */}
      <div className="card" style={{ padding: "1.25rem", marginBottom: 12 }}>
        <p style={{ fontSize: 10, color: "#737373", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 }}>Quick Routes</p>
        <p style={{ fontSize: 12, color: "#8f8f8f", marginBottom: 14 }}>
          Save your frequent stations. On the Rerouting page, one-click buttons will fill these in automatically.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, alignItems: "start" }}>
          <StationInput
            label="🏠 Home Station"
            value={local.home_station}
            onChange={v => setLocal(prev => ({ ...prev, home_station: v }))}
            placeholder="e.g. PUTRA HEIGHTS"
            options={stationOptions}
          />
          <StationInput
            label="🏢 Work Station"
            value={local.work_station}
            onChange={v => setLocal(prev => ({ ...prev, work_station: v }))}
            placeholder="e.g. KLCC"
            options={stationOptions}
          />
        </div>
      </div>

      {/* Route Priority */}
      <div className="card" style={{ padding: "1.25rem", marginBottom: 12 }}>
        <p style={{ fontSize: 10, color: "#737373", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 }}>Default Route Priority</p>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {([
            { v: "fastest",         icon: "⚡", label: "Fastest Route",         desc: "Minimise total travel time — uses per-line speed estimates from GTFS data." },
            { v: "fewest_stops",    icon: "🔢", label: "Fewest Stops",           desc: "Every station has equal weight. May involve more transfers but fewer stops total." },
            { v: "fewest_transfers",icon: "🔄", label: "Fewest Transfers",       desc: "Strongly avoids line changes. Stay on one line as long as possible — great for comfort." },
          ] as const).map(opt => {
            const active = local.priority === opt.v;
            return (
              <button key={opt.v} onClick={() => setPriority(opt.v)} style={{
                display: "flex", alignItems: "flex-start", gap: 12, width: "100%",
                background:   active ? "rgba(59,130,246,0.1)" : "rgba(0,0,0,0.02)",
                border:       `1px solid ${active ? "rgba(59,130,246,0.4)" : "rgba(0,0,0,0.07)"}`,
                borderRadius: 10, padding: "12px 14px", cursor: "pointer", textAlign: "left",
                transition: "all 0.15s",
              }}>
                <span style={{ fontSize: 18, flexShrink: 0, lineHeight: 1 }}>{opt.icon}</span>
                <div>
                  <p style={{ fontSize: 13, fontWeight: 600, color: active ? "#93c5fd" : "#5f5f5f", margin: 0 }}>{opt.label}</p>
                  <p style={{ fontSize: 11, color: "#737373", margin: "3px 0 0", lineHeight: 1.5 }}>{opt.desc}</p>
                </div>
                <div style={{ marginLeft: "auto", width: 16, height: 16, borderRadius: "50%", border: `2px solid ${active ? "#3b82f6" : "rgba(0,0,0,0.15)"}`, background: active ? "#3b82f6" : "transparent", flexShrink: 0, marginTop: 2, transition: "all 0.15s" }} />
              </button>
            );
          })}
        </div>
      </div>

      {/* Shelter Preference */}
      <div className="card" style={{ padding: "1.25rem", marginBottom: 12 }}>
        <p style={{ fontSize: 10, color: "#737373", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 }}>Weather & Comfort</p>
        <button onClick={toggleShelter} style={{
          display: "flex", alignItems: "center", gap: 14, width: "100%",
          background:   local.prefer_shelter ? "rgba(245,158,11,0.08)" : "rgba(0,0,0,0.02)",
          border:       `1px solid ${local.prefer_shelter ? "rgba(245,158,11,0.35)" : "rgba(0,0,0,0.07)"}`,
          borderRadius: 10, padding: "14px 16px", cursor: "pointer", textAlign: "left",
          transition: "all 0.15s",
        }}>
          <span style={{ fontSize: 22, flexShrink: 0 }}>🌧</span>
          <div style={{ flex: 1 }}>
            <p style={{ fontSize: 13, fontWeight: 600, color: local.prefer_shelter ? "#f59e0b" : "#5f5f5f", margin: 0 }}>Prefer Sheltered Routes</p>
            <p style={{ fontSize: 11, color: "#737373", margin: "3px 0 0", lineHeight: 1.5 }}>
              Adds a cost penalty to BRT (street-level) and Monorail (open-air elevated) stops.
              The route planner will prefer covered LRT or underground MRT stations even if the journey is slightly longer.
              Useful during rainy season.
            </p>
          </div>
          {/* Toggle */}
          <div style={{ width: 40, height: 22, borderRadius: 99, flexShrink: 0, background: local.prefer_shelter ? "#f59e0b" : "rgba(0,0,0,0.1)", position: "relative", transition: "background 0.2s" }}>
            <div style={{ position: "absolute", top: 4, left: local.prefer_shelter ? 22 : 4, width: 14, height: 14, borderRadius: "50%", background: "#fff", transition: "left 0.2s" }} />
          </div>
        </button>
      </div>

      {/* Accessibility & Mobility */}
      <div className="card" style={{ padding: "1.25rem", marginBottom: 12 }}>
        <p style={{ fontSize: 10, color: "#737373", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 12 }}>Accessibility & Mobility</p>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {([
            { on: local.require_wheelchair, toggle: toggleWheelchair, icon: "♿", accent: "#3b82f6",
              label: "Step-free / OKU accessible", desc: "Excludes stations without step-free lift access from routes (e.g. the Monorail). If your start or end is inaccessible, you'll be told." },
            { on: local.require_tactile, toggle: toggleTactile, icon: "🦯", accent: "#8b5cf6",
              label: "Blind — tactile guidance alerts", desc: "Warns when a route uses stations whose tactile guiding path may not reach outside. Does not exclude stations — pair with Voice Help for spoken directions." },
            { on: local.prefer_quiet, toggle: toggleQuiet, icon: "💺", accent: "#059669",
              label: "Prefer a quieter route (more likely a seat)", desc: "Uses historical ridership (data.gov.my, Jan–Jul 2026) to prefer less-crowded segments. Based on past daily averages, not live or time-of-day — does not guarantee a seat." },
            { on: local.prefer_safer_walk, toggle: toggleSaferWalk, icon: "🚶", accent: "#d97706",
              label: "Warn about the walk to/from the station", desc: "Flags stations whose 100–200 m walking approach scored low on lighting, passers-by, crossings, bushes and traffic barriers. Compiled from Street View imagery (~2024) by one surveyor — an observational estimate, not verified crime data. Advisory only; your route is unchanged." },
          ] as const).map(opt => (
            <button key={opt.label} onClick={opt.toggle} style={{
              display: "flex", alignItems: "center", gap: 14, width: "100%",
              background:   opt.on ? `${opt.accent}14` : "rgba(0,0,0,0.02)",
              border:       `1px solid ${opt.on ? `${opt.accent}66` : "rgba(0,0,0,0.07)"}`,
              borderRadius: 10, padding: "14px 16px", cursor: "pointer", textAlign: "left",
              transition: "all 0.15s",
            }}>
              <span style={{ fontSize: 22, flexShrink: 0 }}>{opt.icon}</span>
              <div style={{ flex: 1 }}>
                <p style={{ fontSize: 13, fontWeight: 600, color: opt.on ? opt.accent : "#5f5f5f", margin: 0 }}>{opt.label}</p>
                <p style={{ fontSize: 11, color: "#737373", margin: "3px 0 0", lineHeight: 1.5 }}>{opt.desc}</p>
              </div>
              <div style={{ width: 40, height: 22, borderRadius: 99, flexShrink: 0, background: opt.on ? opt.accent : "rgba(0,0,0,0.1)", position: "relative", transition: "background 0.2s" }}>
                <div style={{ position: "absolute", top: 4, left: opt.on ? 22 : 4, width: 14, height: 14, borderRadius: "50%", background: "#fff", transition: "left 0.2s" }} />
              </div>
            </button>
          ))}
        </div>

        {/* Max walking (bucketed selector) */}
        <div style={{ marginTop: 12, borderTop: "1px solid rgba(0,0,0,0.06)", paddingTop: 14 }}>
          <p style={{ fontSize: 13, fontWeight: 600, color: local.max_walk_minutes ? "#0ea5e9" : "#5f5f5f", margin: "0 0 3px" }}>🚶 Max walking</p>
          <p style={{ fontSize: 11, color: "#737373", margin: "0 0 10px", lineHeight: 1.5 }}>
            Prefer routes within a walking limit (approximate — mostly counts line transfers). If no route fits, the least-walking option is shown instead.
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {[{ v: 0, l: "No limit" }, { v: 5, l: "~5 min" }, { v: 10, l: "~10 min" }, { v: 15, l: "~15 min" }].map(opt => {
              const active = local.max_walk_minutes === opt.v;
              return (
                <button key={opt.v} onClick={() => setMaxWalk(opt.v)} style={{
                  fontSize: 12, fontWeight: active ? 700 : 500,
                  padding: "8px 16px", borderRadius: 8, cursor: "pointer",
                  background: active ? "#0ea5e9" : "rgba(0,0,0,0.02)",
                  color: active ? "#fff" : "#5f5f5f",
                  border: `1px solid ${active ? "#0ea5e9" : "rgba(0,0,0,0.07)"}`,
                  transition: "all 0.15s",
                }}>
                  {opt.l}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Avoid Lines */}
      <div className="card" style={{ padding: "1.25rem", marginBottom: 20 }}>
        <p style={{ fontSize: 10, color: "#737373", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>Always Avoid These Lines</p>
        <p style={{ fontSize: 12, color: "#8f8f8f", marginBottom: 14 }}>
          Selected lines will be excluded from all route searches by default. You can still override this on a per-trip basis.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {ALL_LINES.map(line => {
            const avoided = local.avoid_lines.includes(line.id);
            return (
              <button key={line.id} onClick={() => toggleLine(line.id)} style={{
                display: "flex", alignItems: "center", gap: 10, width: "100%",
                background:   avoided ? "rgba(239,68,68,0.06)" : "rgba(0,0,0,0.02)",
                border:       `1px solid ${avoided ? "rgba(239,68,68,0.3)" : "rgba(0,0,0,0.07)"}`,
                borderRadius: 9, padding: "10px 12px", cursor: "pointer", textAlign: "left",
                transition: "all 0.15s",
              }}>
                <div style={{ width: 4, height: 28, borderRadius: 99, background: line.color, flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: avoided ? "#ef4444" : "#5f5f5f", textDecoration: avoided ? "line-through" : "none" }}>{line.name}</span>
                  <span style={{ fontSize: 10, color: "#8f8f8f", marginLeft: 8 }}>{line.note}</span>
                </div>
                <div style={{
                  width: 18, height: 18, borderRadius: 4, border: `2px solid ${avoided ? "#ef4444" : "rgba(0,0,0,0.15)"}`,
                  background: avoided ? "#ef4444" : "transparent", flexShrink: 0,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  transition: "all 0.15s",
                }}>
                  {avoided && <span style={{ color: "#fff", fontSize: 10, fontWeight: 700 }}>✕</span>}
                </div>
              </button>
            );
          })}
        </div>
        {local.avoid_lines.length > 0 && (
          <p style={{ fontSize: 11, color: "#ef4444", marginTop: 10 }}>
            ⚠ {local.avoid_lines.length} line{local.avoid_lines.length > 1 ? "s" : ""} excluded — some routes may not be available.
          </p>
        )}
      </div>

      {/* Save / Reset */}
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <button className="btn-primary" onClick={save} disabled={saving} style={{ flex: 1 }}>
          {saving
            ? <><span className="anim-spin" style={{ width: 12, height: 12, border: "2px solid rgba(255,255,255,0.4)", borderTopColor: "#fff", borderRadius: "50%", display: "inline-block" }} /> Saving…</>
            : "Save Preferences →"}
        </button>
        <button onClick={reset} style={{ background: "none", border: "1px solid rgba(0,0,0,0.08)", color: "#737373", fontSize: 11, padding: "9px 16px", borderRadius: 8, cursor: "pointer" }}>
          Reset defaults
        </button>
      </div>

      {saved && (
        <div className="anim-fade-in" style={{ marginTop: 12, padding: "10px 14px", background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.25)", borderRadius: 8, fontSize: 12, color: "#22c55e" }}>
          ✓ Preferences saved — they'll be applied automatically on the Rerouting page.
        </div>
      )}
      {error && (
        <div className="anim-fade-in" style={{ marginTop: 12, padding: "10px 14px", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", borderRadius: 8, fontSize: 12, color: "#ef4444" }}>
          {error}
        </div>
      )}
    </div>
  );
}
