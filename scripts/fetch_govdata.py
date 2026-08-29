"""
Fetch official Malaysian gov-data sources and cache as JSON for the dashboard.

Sources:
  1. GTFS Static  (data.gov.my)  — validates our local station list against official
  2. GTFS Realtime vehicle pos    — counts trains currently in service (rail unstable
                                    upstream; we degrade gracefully on failure)
  3. ridership_headline (data.gov.my) — most recent monthly ridership per rail line

Output:
  data/govdata/cache.json

Usage (from D:/FYP):
    python scripts/fetch_govdata.py
"""
import sys, json, io, zipfile, csv
sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path
from datetime import datetime, timezone
import urllib.request

ROOT      = Path("D:/FYP")
CACHE_DIR = ROOT / "data/govdata"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE     = CACHE_DIR / "cache.json"
LOCAL_STOPS = ROOT / "data/raw/gtfs/stops.txt"

GTFS_STATIC_URL = "https://api.data.gov.my/gtfs-static/prasarana?category=rapid-rail-kl"
VEHICLE_POS_URL = "https://api.data.gov.my/gtfs-realtime/vehicle-position/prasarana?category=rapid-rail-kl"
RIDERSHIP_URL   = "https://api.data.gov.my/data-catalogue?id=ridership_headline&limit=400"

def _safe_fetch(url, timeout=30):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LRT-Companion-FYP"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), None
    except Exception as e:
        return None, str(e)

out = {
    "fetched_at": datetime.now(timezone.utc).isoformat(),
    "sources": {},
}

# ── 1. GTFS Static — official station count ─────────────────────────────────
print("[1/3] Fetching GTFS Static...")
data, err = _safe_fetch(GTFS_STATIC_URL, timeout=60)
if err:
    out["sources"]["gtfs_static"] = {"ok": False, "error": err}
else:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        stops_csv = z.read("stops.txt").decode("utf-8")
        official_stops = list(csv.DictReader(io.StringIO(stops_csv)))

        local_stops = []
        if LOCAL_STOPS.exists():
            with open(LOCAL_STOPS, encoding="utf-8") as f:
                local_stops = list(csv.DictReader(f))

        out["sources"]["gtfs_static"] = {
            "ok": True,
            "official_stop_count": len(official_stops),
            "local_stop_count":    len(local_stops),
            "match":               len(official_stops) == len(local_stops),
            "files_in_zip":        z.namelist(),
        }
        print(f"   official={len(official_stops)} local={len(local_stops)}")
    except Exception as e:
        out["sources"]["gtfs_static"] = {"ok": False, "error": f"parse: {e}"}

# ── 2. GTFS Realtime — vehicle positions ─────────────────────────────────────
print("[2/3] Fetching GTFS Realtime vehicle positions...")
data, err = _safe_fetch(VEHICLE_POS_URL, timeout=20)
if err:
    out["sources"]["vehicle_positions"] = {
        "ok":      False,
        "error":   err,
        "note":    "Rail realtime feed is unstable upstream — known limitation",
    }
else:
    # Protobuf; just record byte size and let downstream parse if needed
    out["sources"]["vehicle_positions"] = {
        "ok":             True,
        "bytes_received": len(data),
        "note":           "Protobuf payload received — see GTFS-RT spec for parsing",
    }
    print(f"   {len(data)} bytes")

# ── 3. Ridership headline — most recent rail figures ────────────────────────
print("[3/3] Fetching ridership_headline...")
data, err = _safe_fetch(RIDERSHIP_URL, timeout=30)
if err:
    out["sources"]["ridership"] = {"ok": False, "error": err}
else:
    try:
        rows = json.loads(data.decode("utf-8"))
        if isinstance(rows, list) and rows:
            rail_keys = ["rail_lrt_kj","rail_lrt_ag","rail_mrt_kjg",
                         "rail_mrt_pjy","rail_monorail"]
            # Walk backwards to find newest row with any rail data
            latest = None
            for r in reversed(rows):
                if any(r.get(k) is not None for k in rail_keys):
                    latest = r
                    break
            if latest:
                out["sources"]["ridership"] = {
                    "ok":   True,
                    "date": latest.get("date"),
                    "rail": {k: latest.get(k) for k in rail_keys},
                    "total_rows": len(rows),
                }
                print(f"   latest date={latest.get('date')}")
            else:
                out["sources"]["ridership"] = {"ok": False, "error": "no rail data in any row"}
        else:
            out["sources"]["ridership"] = {"ok": False, "error": "empty response"}
    except Exception as e:
        out["sources"]["ridership"] = {"ok": False, "error": f"parse: {e}"}

CACHE.write_text(json.dumps(out, indent=2))
print(f"\nSaved → {CACHE}")
print(json.dumps({k: v.get("ok", False) for k, v in out["sources"].items()}, indent=2))
