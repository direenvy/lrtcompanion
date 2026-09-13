/**
 * CARTO basemap for both Leaflet maps. The tile key is public by nature (it
 * ships in every tile request), so it lives in NEXT_PUBLIC_CARTO_KEY and is
 * domain-restricted in the CARTO dashboard rather than kept secret. Without a
 * key the URL still works — CARTO serves a watermarked tile instead of failing.
 */
const KEY = process.env.NEXT_PUBLIC_CARTO_KEY;

export const TILE_URL =
  "https://{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}{r}.png"
  + (KEY ? `?key=${KEY}` : "");

export const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, '
  + '&copy; <a href="https://carto.com/attributions">CARTO</a>';

export const TILE_SUBDOMAINS = "abcd";
export const TILE_MAX_ZOOM = 20;
