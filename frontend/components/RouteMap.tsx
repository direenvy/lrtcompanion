"use client";
/**
 * RouteMap — renders the rerouting result on an OpenStreetMap base layer.
 *
 * Uses react-leaflet with SSR disabled (dynamic-imported by the parent).
 * Each segment gets its own coloured polyline; interchange stations get
 * a larger orange marker, regular stations get small dot circle markers.
 */
import { useEffect } from "react";
import { MapContainer, TileLayer, Polyline, CircleMarker, Popup, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { TILE_URL, TILE_ATTRIBUTION, TILE_SUBDOMAINS, TILE_MAX_ZOOM } from "@/lib/tiles";

const LINE_COLOR: Record<string, string> = {
  KJ:  "#ef4444",
  AG:  "#f97316",
  PH:  "#ec4899",
  KGL: "#22c55e",
  PYL: "#eab308",
  MR:  "#84cc16",
  BRT: "#10b981",
  SA:  "#38bdf8",
};

interface StationPoint {
  name:    string;
  lat:     number;
  lon:     number;
  stop_id: string;
}

interface Segment {
  line:           string;
  from:           string;
  to:             string;
  station_points: StationPoint[];
  n_stops:        number;
  minutes:        number | null;
}

interface PlaceNote {
  field:   string;   // "origin" | "destination"
  place:   string;
  lat:     number;
  lon:     number;
  station: string;
  walk_minutes?: number;
}

interface DisruptedPoint {
  stop_id: string;
  name:    string;
  lat:     number;
  lon:     number;
}

interface RouteMapProps {
  segments:          Segment[];
  disrupted_avoided: string[];
  disrupted_points?: DisruptedPoint[];
  /** The normal-but-disrupted route, drawn as a red dashed ghost line so
      users see the broken path alongside the recommended detour. */
  disrupted_route?:  Segment[];
  places?:           PlaceNote[];
}

/** Re-fits the map bounds whenever segments change. */
function FitBounds({ segments, places, disruptedPoints }: {
  segments: Segment[]; places?: PlaceNote[]; disruptedPoints?: DisruptedPoint[];
}) {
  const map = useMap();
  useEffect(() => {
    const allPts: { lat: number; lon: number }[] = [
      ...segments.flatMap(s => s.station_points ?? []),
      ...(places ?? []),
      ...(disruptedPoints ?? []),
    ];
    if (allPts.length < 2) return;
    const lats = allPts.map(p => p.lat);
    const lons = allPts.map(p => p.lon);
    map.fitBounds(
      [[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]],
      { padding: [40, 40] }
    );
  }, [segments, places, disruptedPoints, map]);
  return null;
}

export default function RouteMap({ segments, disrupted_avoided, disrupted_points, disrupted_route, places }: RouteMapProps) {
  // Collect interchange station names (appear in more than one segment boundary)
  const boundaries = new Set<string>();
  segments.forEach((seg, i) => {
    if (i > 0) boundaries.add(seg.from);
  });

  // Centre on KL if no points yet
  const allPts = segments.flatMap(s => s.station_points ?? []);
  const center: [number, number] = allPts.length
    ? [allPts[0].lat, allPts[0].lon]
    : [3.1478, 101.6953];

  // Key the container by route identity: a new route mounts a FRESH map div,
  // so Leaflet never re-initialises a container it already owns
  // ("Map container is being reused by another instance").
  const mapKey = segments.map(s => `${s.from}-${s.to}`).join("|") || "empty";

  return (
    <MapContainer
      key={mapKey}
      center={center}
      zoom={13}
      style={{ height: "100%", width: "100%", borderRadius: 12, background: "#e8e8e8" }}
      zoomControl={true}
      scrollWheelZoom={true}
    >
      <TileLayer
        attribution={TILE_ATTRIBUTION}
        url={TILE_URL}
        subdomains={TILE_SUBDOMAINS}
        maxZoom={TILE_MAX_ZOOM}
      />

      <FitBounds segments={segments} places={places} disruptedPoints={disrupted_points} />

      {/* Ghost of the normal-but-disrupted route: red dashed, drawn UNDER the
          recommended route so both are visible at once (Waze-style) */}
      {(disrupted_route ?? []).map((seg, i) => {
        const pts = seg.station_points ?? [];
        if (pts.length < 2) return null;
        return (
          <Polyline
            key={`ghost-${i}`}
            positions={pts.map(p => [p.lat, p.lon] as [number, number])}
            pathOptions={{ color: "#ef4444", weight: 4, opacity: 0.45, dashArray: "10 10" }}
          >
            <Popup>
              <div style={{ fontFamily: "system-ui", fontSize: 12, lineHeight: 1.5 }}>
                <strong style={{ color: "#ef4444" }}>⚠ Normal route — disrupted</strong><br />
                Currently affected by a reported disruption; the coloured route avoids it.
              </div>
            </Popup>
          </Polyline>
        );
      })}

      {/* Disrupted stations the route detours around — shown so users can SEE
          what they're avoiding, even though it's not on the route line */}
      {(disrupted_points ?? []).map((dp) => (
        <CircleMarker
          key={`disrupted-${dp.stop_id}`}
          center={[dp.lat, dp.lon]}
          radius={9}
          pathOptions={{ color: "#ef4444", fillColor: "#ef4444", fillOpacity: 0.35, weight: 2, dashArray: "4 4" }}
        >
          <Popup>
            <div style={{ fontFamily: "system-ui", fontSize: 12, lineHeight: 1.5 }}>
              <strong style={{ color: "#ef4444" }}>⚠ {dp.name}</strong><br />
              Reported disrupted — this route avoids it.
            </div>
          </Popup>
        </CircleMarker>
      ))}

      {/* Walking legs from geocoded places (malls, landmarks) to the rail endpoints */}
      {(places ?? []).map((pl) => {
        const allPts = segments.flatMap(s => s.station_points ?? []);
        if (!allPts.length) return null;
        const target = pl.field === "destination" ? allPts[allPts.length - 1] : allPts[0];
        return (
          <div key={`place-${pl.field}`}>
            <Polyline
              positions={[[pl.lat, pl.lon], [target.lat, target.lon]]}
              pathOptions={{ color: "#000000", weight: 4, opacity: 0.85, dashArray: "8 10" }}
            />
            <CircleMarker
              center={[pl.lat, pl.lon]}
              radius={10}
              pathOptions={{ color: "#ffffff", fillColor: "#000000", fillOpacity: 1, weight: 2 }}
            >
              <Popup>
                <div style={{ fontFamily: "system-ui", fontSize: 12, lineHeight: 1.5 }}>
                  <strong>📍 {pl.place}</strong><br />
                  Walk to {pl.station}{pl.walk_minutes ? ` (~${pl.walk_minutes} min)` : ""}<br />
                  <a
                    href={`https://www.google.com/maps/dir/?api=1&origin=${pl.lat},${pl.lon}&destination=${encodeURIComponent(pl.station + " station")}&travelmode=walking`}
                    target="_blank" rel="noopener noreferrer"
                  >
                    Walking directions ↗
                  </a>
                </div>
              </Popup>
            </CircleMarker>
          </div>
        );
      })}

      {/* Dashed walking connectors between consecutive segments whose
          stations are physically apart (link bridges / street walks) */}
      {segments.slice(0, -1).map((seg, i) => {
        const pts  = seg.station_points ?? [];
        const next = segments[i + 1]?.station_points ?? [];
        const a = pts[pts.length - 1];
        const b = next[0];
        if (!a || !b) return null;
        // Skip same-platform transfers (< ~45 m apart)
        if (Math.abs(a.lat - b.lat) < 4e-4 && Math.abs(a.lon - b.lon) < 4e-4) return null;
        return (
          <Polyline
            key={`walk-${i}`}
            positions={[[a.lat, a.lon], [b.lat, b.lon]]}
            pathOptions={{ color: "#737373", weight: 3, opacity: 0.9, dashArray: "6 8" }}
          >
            <Popup>
              <div style={{ fontFamily: "system-ui", fontSize: 12, lineHeight: 1.5 }}>
                <strong>🚶 Walking transfer</strong><br />
                {a.name} → {b.name}
              </div>
            </Popup>
          </Polyline>
        );
      })}

      {segments.map((seg, si) => {
        const color = LINE_COLOR[seg.line] ?? "#737373";
        const pts   = seg.station_points ?? [];
        if (pts.length < 2) return null;

        const positions: [number, number][] = pts.map(p => [p.lat, p.lon]);

        return (
          <div key={si}>
            {/* Route polyline */}
            <Polyline
              positions={positions}
              pathOptions={{ color, weight: 4, opacity: 0.9 }}
            />

            {/* Red dashed overlay on the stretch through a disrupted station —
                marks the broken part of the line when viewing the
                "via disruption" route */}
            {pts.map((pt, pi) => {
              if (!disrupted_avoided.includes(pt.stop_id)) return null;
              const a = pts[Math.max(0, pi - 1)];
              const b = pts[Math.min(pts.length - 1, pi + 1)];
              return (
                <Polyline
                  key={`disr-${si}-${pi}`}
                  positions={[[a.lat, a.lon], [pt.lat, pt.lon], [b.lat, b.lon]]}
                  pathOptions={{ color: "#ef4444", weight: 6, opacity: 0.9, dashArray: "6 8" }}
                >
                  <Popup>
                    <div style={{ fontFamily: "system-ui", fontSize: 12, lineHeight: 1.5 }}>
                      <strong style={{ color: "#ef4444" }}>⚠ Disrupted stretch</strong><br />
                      Passes through {pt.name} — reported disruption.
                    </div>
                  </Popup>
                </Polyline>
              );
            })}

            {/* Station markers */}
            {pts.map((pt, pi) => {
              const isEnd      = pi === 0 || pi === pts.length - 1;
              const isInterchg = boundaries.has(pt.name);
              const isDisrupted = disrupted_avoided.includes(pt.stop_id);

              const markerColor = isDisrupted ? "#ef4444"
                : isInterchg    ? "#f59e0b"
                : isEnd         ? color
                : color;

              const radius      = isEnd || isInterchg ? 7 : 4;
              const fillOpacity = isEnd || isInterchg ? 1  : 0.7;
              const weight      = isEnd || isInterchg ? 2  : 1;

              return (
                <CircleMarker
                  key={`${si}-${pi}`}
                  center={[pt.lat, pt.lon]}
                  radius={radius}
                  pathOptions={{
                    color:        "#ffffff",
                    fillColor:    markerColor,
                    fillOpacity,
                    weight,
                  }}
                >
                  <Popup>
                    <div style={{ fontFamily: "system-ui", fontSize: 12, lineHeight: 1.5 }}>
                      <strong>{pt.name}</strong><br />
                      <span style={{ color: "#666" }}>{seg.line} line</span>
                      {isDisrupted && <><br /><span style={{ color: "#ef4444", fontWeight: 600 }}>⚠ Disrupted</span></>}
                      {isInterchg  && <><br /><span style={{ color: "#f59e0b", fontWeight: 600 }}>⇄ Interchange</span></>}
                    </div>
                  </Popup>
                </CircleMarker>
              );
            })}
          </div>
        );
      })}
    </MapContainer>
  );
}
