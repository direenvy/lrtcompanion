"use client";
/**
 * NetworkMap — the full Klang Valley rail network: every line drawn as a
 * coloured polyline in correct route order, every station a dot with a popup.
 * Data from GET /api/reroute/network (built from official GTFS). SSR disabled
 * by the parent (Leaflet needs the browser).
 */
import { useEffect, useState } from "react";
import { MapContainer, TileLayer, Polyline, CircleMarker, Popup } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { getNetworkMap } from "@/lib/api";

interface Station { stop_id: string; name: string; lat: number; lon: number; }
interface Line { line_id: string; name: string; color: string; stations: Station[]; }

export default function NetworkMap() {
  const [lines, setLines]   = useState<Line[]>([]);
  const [error, setError]   = useState(false);
  // Multi-select filter: empty set = all lines shown. Click a chip to add it
  // to the selection, click it again (or press its × ) to remove. "All lines"
  // clears the selection to show everything.
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    getNetworkMap()
      .then((d) => setLines(d.lines ?? []))
      .catch(() => setError(true));
  }, []);

  if (error) return <p style={{ fontSize: 12, color: "#b45309" }}>Could not load the network map.</p>;
  if (!lines.length) return <p style={{ fontSize: 12, color: "#8f8f8f" }}>Loading network…</p>;

  const toggle = (id: string) =>
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  const clearAll = () => setSelected(new Set());

  const showingAll = selected.size === 0;
  const shown = showingAll ? lines : lines.filter((l) => selected.has(l.line_id));

  return (
    <div>
      {/* Line legend / multi-select filter */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
        <button onClick={clearAll} style={{
          fontSize: 11, padding: "4px 10px", borderRadius: 99, cursor: "pointer",
          border: `1px solid ${showingAll ? "#000" : "rgba(0,0,0,0.15)"}`,
          background: showingAll ? "#000" : "transparent",
          color: showingAll ? "#fff" : "#737373",
        }}>All lines</button>
        {lines.map((l) => {
          const on = selected.has(l.line_id);
          return (
            <button key={l.line_id} onClick={() => toggle(l.line_id)}
              title={on ? `Hide ${l.name}` : `Show ${l.name}`}
              style={{
                fontSize: 11, padding: "4px 10px", borderRadius: 99, cursor: "pointer",
                display: "inline-flex", alignItems: "center", gap: 6,
                border: `1px solid ${on ? l.color : "rgba(0,0,0,0.12)"}`,
                background: on ? `${l.color}22` : "transparent",
                color: on ? "#000" : "#737373",
                fontWeight: on ? 600 : 400,
              }}>
              <span style={{ width: 9, height: 9, borderRadius: "50%", background: l.color }} />
              {l.name.replace(/^(LRT|MRT|KL|BRT)\s/, "")} <span style={{ color: "#a3a3a3" }}>({l.stations.length})</span>
              {on && (
                <span
                  role="button"
                  aria-label={`Remove ${l.name}`}
                  onClick={(e) => { e.stopPropagation(); toggle(l.line_id); }}
                  style={{
                    marginLeft: 2, width: 14, height: 14, borderRadius: "50%",
                    background: "rgba(0,0,0,0.08)", color: "#000",
                    display: "inline-flex", alignItems: "center", justifyContent: "center",
                    fontSize: 10, lineHeight: 1, cursor: "pointer",
                  }}
                >×</span>
              )}
            </button>
          );
        })}
      </div>
      {!showingAll && (
        <p style={{ fontSize: 10, color: "#737373", marginTop: -4, marginBottom: 8 }}>
          Showing {selected.size} of {lines.length} lines. Click any chip to toggle, or "All lines" to reset.
        </p>
      )}

      <div style={{ height: 460, borderRadius: 12, overflow: "hidden", border: "1px solid rgba(0,0,0,0.08)" }}>
        <MapContainer center={[3.10, 101.65]} zoom={11}
          style={{ height: "100%", width: "100%", background: "#e8e8e8" }} scrollWheelZoom>
          <TileLayer
            attribution='&copy; OpenStreetMap'
            url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
          />
          {shown.map((l) => {
            const pts = l.stations.map((s) => [s.lat, s.lon] as [number, number]);
            return (
              <div key={l.line_id}>
                <Polyline positions={pts} pathOptions={{ color: l.color, weight: 3.5, opacity: 0.85 }} />
                {l.stations.map((s) => (
                  <CircleMarker key={s.stop_id} center={[s.lat, s.lon]} radius={4}
                    pathOptions={{ color: "#fff", fillColor: l.color, fillOpacity: 1, weight: 1.5 }}>
                    <Popup>
                      <div style={{ fontFamily: "system-ui", fontSize: 12, lineHeight: 1.5 }}>
                        <strong>{s.name}</strong>{" "}
                        <span style={{ color: l.color, fontWeight: 700 }}>({s.stop_id})</span><br />
                        <span style={{ color: "#666" }}>{l.name}</span>
                      </div>
                    </Popup>
                  </CircleMarker>
                ))}
              </div>
            );
          })}
        </MapContainer>
      </div>
      <p style={{ fontSize: 10, color: "#8f8f8f", marginTop: 6 }}>
        {lines.reduce((n, l) => n + l.stations.length, 0)} stations · {lines.length} lines · official GTFS data.
        Tap a line above to isolate it; click any station for its name and code (e.g. KJ13).
      </p>
    </div>
  );
}
