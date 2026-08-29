"""
Smart O-D Rerouting Agent
Builds a station graph from GTFS data, removes disrupted segments,
and finds the best alternative route using Dijkstra.
"""

import csv
import math
from pathlib import Path
import networkx as nx
from rapidfuzz import process, fuzz

# Paths resolve from THIS file's location so the code works on any host
# (local Windows, Render Linux, CI runners), not just the author's machine.
# backend/agents/rerouting_agent.py -> up 2 = project root -> data/...
_DATA = Path(__file__).resolve().parent.parent.parent / "data"

GTFS_DIR = _DATA / "raw" / "gtfs"

# Manually-curated OKU / wheelchair accessibility overlay. Kept SEPARATE from
# the GTFS feed (which can be refreshed and overwrite edits) and carries its own
# provenance columns (source, verified_date) so the claim is auditable. The
# GTFS `isOKU` column is hard-coded true for every stop and is NOT trusted.
ACCESS_FILE = _DATA / "raw" / "accessibility" / "oku_stations.csv"

# Per-segment historical busyness (0..1), built offline from data.gov.my O-D
# ridership by scripts/build_segment_busyness.py. Used by "prefer_quiet".
SEGMENT_BUSYNESS_FILE = _DATA / "govdata" / "segment_busyness.json"

_TRUE_TOKENS  = {"true", "yes", "y", "1", "accessible", "ok"}
_FALSE_TOKENS = {"false", "no", "n", "0", "inaccessible"}


def _parse_access(val: str):
    """Tri-state: True (accessible), False (not accessible), None (unverified).
    Unknown is NEVER silently treated as accessible — a wheelchair user's
    safety depends on this being real data, not an optimistic default."""
    t = (val or "").strip().lower()
    if t in _TRUE_TOKENS:
        return True
    if t in _FALSE_TOKENS:
        return False
    return None


def _accessible_sibling(resolved_id: str, query: str, stops: dict) -> str | None:
    """When wheelchair mode blocks the resolved platform of an interchange, find
    an accessible platform of the SAME station. E.g. 'KL SENTRAL' resolves to the
    Monorail platform (inaccessible), but the Kelana Jaya 'KL SENTRAL - REDONE'
    platform is accessible — a wheelchair user CAN use KL Sentral, so don't block
    the whole station just because one platform is not step-free."""
    def base(n: str) -> str:
        return n.split(" - ")[0].strip().upper()
    targets = {base(stops[resolved_id]["name"])}
    q = (query or "").strip().upper()
    if q:
        targets.add(q)
        targets.add(base(q))
    for sid, info in stops.items():
        if info.get("wheelchair") is False:
            continue
        nm = info["name"].upper()
        if nm in targets or base(nm) in targets:
            return sid
    return None


def _load_accessibility() -> dict[str, dict]:
    """stop_id -> {'wheelchair': T/F/None, 'tactile': T/F/None} from the manual
    overlay. `tactile` = blind tactile guiding path continuous to OUTSIDE the
    station (per PULSE). Missing file/rows leave a station as None (unverified)."""
    access: dict[str, dict] = {}
    if not ACCESS_FILE.exists():
        return access
    try:
        with ACCESS_FILE.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                sid = (row.get("stop_id") or "").strip().upper()
                if sid:
                    access[sid] = {
                        "wheelchair": _parse_access(row.get("wheelchair_accessible", "")),
                        "tactile":    _parse_access(row.get("blind_tactile", "")),
                    }
    except Exception:
        pass
    return access

# FALLBACK travel times per line (minutes per stop) — real per-edge minutes
# come from stop_times.txt; these apply only to edges missing schedule data.
LINE_TRAVEL_TIME = {
    "KJ": 2.5,
    "AG": 2.5,
    "PH": 2.5,
    "KGL": 3.0,
    "PYL": 3.0,
    "MR": 2.0,
    "BRT": 3.0,
    "SA":  3.0,
}

INTERCHANGE_PENALTY = 5  # minutes for transferring between lines (default)

# Cross-line interchange overrides. Two uses:
#  - stations with DIFFERENT names the automatic same-name rule cannot see
#  - same-name stations whose transfer is an out-of-station WALK, so the
#    default 5-min same-station weight must be overridden upward
# (name_a, name_b, walk_minutes)
NAMED_INTERCHANGES: list[tuple[str, str, float]] = [
    ("GLENMARIE",    "GLENMARIE 2",  8.0),   # KJ <-> LRT3: direct link bridge
    ("BANDAR UTAMA", "BANDAR UTAMA", 12.0),  # KGL <-> LRT3: exit + street walk + re-entry
    ("USJ 7",        "USJ7",         5.0),   # KJ <-> BRT: integrated station
]

# Extra weight added to an EXPOSED interchange transfer (not weather-covered)
# when prefer_shelter is on, so Dijkstra favours routes whose transfers stay dry.
INTERCHANGE_EXPOSED_PENALTY = 8.0

# Commuter initialisms / nicknames that don't appear verbatim in GTFS. Resolved
# to the official station name so they work offline and resolve consistently
# (no geocoding fallback, no platform ambiguity). Keys are UPPER-cased queries.
_STATION_ALIASES: dict[str, str] = {
    "TRX":        "TUN RAZAK EXCHANGE",
    "KL SENTRAL": "KL SENTRAL - REDONE",   # GTFS suffixes the KJ platform
    "KLSENTRAL":  "KL SENTRAL - REDONE",
    "TTDI":       "TAMAN TUN DR ISMAIL",
    "BST":        "BANDAR TASIK SELATAN",
    "UM":         "UNIVERSITI",
}

# Interchange weather-shelter data — SOURCE OF TRUTH is the surveyed CSV
# (data/raw/shelter/interchange_shelter.csv, column `covered`). A transfer is
# EXPOSED only where the survey marked it not-covered. Kept out of GTFS as an
# overlay, like the OKU accessibility data.
_SHELTER_CSV = (Path(__file__).resolve().parent.parent.parent
                / "data" / "raw" / "shelter" / "interchange_shelter.csv")


def _norm_station(name: str) -> str:
    """Normalise a station name for matching across sources (drop spaces,
    hyphens and case) so 'USJ-7' / 'USJ 7' / 'USJ7' all compare equal."""
    return "".join(ch for ch in name.upper() if ch.isalnum())


def _load_exposed_interchanges() -> set[str]:
    """Normalised names of interchanges the survey marked NOT covered."""
    exposed: set[str] = set()
    try:
        import csv as _csv
        with _SHELTER_CSV.open(encoding="utf-8-sig") as f:
            for row in _csv.DictReader(f):
                if (row.get("covered") or "").strip().lower() != "yes":
                    exposed.add(_norm_station(row["station"]))
    except Exception as e:
        print(f"[Reroute] interchange shelter data unavailable: {e}")
    return exposed


_EXPOSED_INTERCHANGES = _load_exposed_interchanges()

# Station walk-safety survey — SOURCE OF TRUTH is the manually-surveyed CSV
# (data/raw/station_walk_safety/station_walk_safety.csv). Five yes/no factors
# per station describe the 100-200 m walking approach from the station exit,
# assessed against the snatch-theft (ragut) pattern.
#
# IMPORTANT — this dataset is a SUBJECTIVE OBSERVATIONAL SURVEY, not measured
# ground truth. It was compiled by one surveyor from Google Street View imagery
# (dated ~2024) rather than on-site visits or police crime statistics, so:
#   * ratings reflect that surveyor's judgement and may differ from another's
#   * Street View imagery lags reality — construction, new lighting, changed
#     frontage and new fencing since capture are not reflected
#   * stations with multiple exits are rated on their WORST exit only
#   * "people_nearby" estimates perceived off-peak activity, which cannot be
#     verified from a daytime still image
# The feature is therefore WARNING-ONLY and never alters rail routing. Treat
# the output as an advisory prompt to stay alert, not a safety guarantee.
_WALK_SAFETY_CSV = (Path(__file__).resolve().parent.parent.parent
                    / "data" / "raw" / "station_walk_safety"
                    / "station_walk_safety.csv")

# Factor column -> the plain-English risk it describes when the answer is "no".
WALK_SAFETY_FACTORS: dict[str, str] = {
    "street_lights":  "poor street lighting",
    "people_nearby":  "few people around in the evening",
    "safe_crossing":  "no safe pedestrian crossing",
    "bushes_nearby":  "overgrown bushes reducing visibility",
    "fenced":         "no barrier between the walkway and traffic",
}

# Score = number of "yes" answers out of 5. Surveyed spread is 2-4, so the
# cut-offs sit either side of 3 rather than at the theoretical extremes.
WALK_SAFETY_GOOD_MIN   = 4      # >= 4 yes  -> good  (no note)
WALK_SAFETY_MEDIUM_MIN = 3      # == 3 yes  -> medium (amber note)
                                # <= 2 yes  -> bad    (red note)


def _load_walk_safety() -> dict[str, dict]:
    """Normalised station name -> {'score', 'level', 'failing', 'code'}.

    Keyed by name, not by the CSV's `code`: the survey zero-pads codes (KJ01)
    while GTFS does not (KJ1), and a physical interchange has ONE walking
    environment regardless of how many platforms share it.
    """
    out: dict[str, dict] = {}
    try:
        import csv as _csv
        with _WALK_SAFETY_CSV.open(encoding="utf-8-sig") as f:
            for row in _csv.DictReader(f):
                answers = {k: (row.get(k) or "").strip().lower()
                           for k in WALK_SAFETY_FACTORS}
                if not all(answers.values()):
                    continue          # partially surveyed row — skip, don't guess
                score   = sum(1 for v in answers.values() if v == "yes")
                failing = [WALK_SAFETY_FACTORS[k]
                           for k, v in answers.items() if v != "yes"]
                level = ("good"   if score >= WALK_SAFETY_GOOD_MIN   else
                         "medium" if score >= WALK_SAFETY_MEDIUM_MIN else "bad")
                entry = {"score": score, "level": level, "failing": failing,
                         "code": (row.get("code") or "").strip().upper(),
                         "area_context": (row.get("area_context") or "").strip()}
                key = _norm_station(row["station"])
                # An interchange surveyed once per line (e.g. USJ 7 as both KJ31
                # and BRT07) can disagree between its exits. Keep the WORSE
                # rating — the survey's own rule is to rate the worst exit, and
                # a safety warning must not be silently softened by row order.
                prev = out.get(key)
                if prev is None or score < prev["score"]:
                    out[key] = entry
    except Exception as e:
        print(f"[Reroute] walk-safety survey unavailable: {e}")
    return out


_WALK_SAFETY = _load_walk_safety()

# Total walking (line transfers + station access on foot) at/above which the
# route is flagged as walk-heavy, so the user is reminded before they set off.
WALK_WARN_MINUTES = 15

# Extra weight added to a transfer edge when "prefer_less_walking" is on, so
# Dijkstra favours routes with fewer / shorter on-foot transfers. Out-of-station
# walks are penalised in proportion to their length (see _build_graph).
WALK_AVERSION_PENALTY = 6

# Max weight (minutes-equivalent) added to the busiest segment when
# "prefer_quiet" is on; a segment's penalty scales with its 0..1 busyness ratio.
QUIET_MAX_PENALTY = 4.0


def _load_segment_busyness() -> dict[str, float]:
    """'STOPA|STOPB' (sorted) -> 0..1 historical busyness ratio. Empty if the
    offline file hasn't been built yet, so routing degrades gracefully."""
    try:
        import json
        data = json.loads(SEGMENT_BUSYNESS_FILE.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        return {}


_SEGMENT_BUSYNESS = _load_segment_busyness()

# Extra per-stop weight added when "prefer_shelter" is on
SHELTER_PENALTY: dict[str, float] = {
    "BRT": 3.0,   # street-level stops — most exposed
    "MR":  1.5,   # open-air elevated monorail platforms
}

# ── Bridging bus lookup (sourced from RapidKL emergency SOPs & Prasarana docs) ──
# When a rail line is disrupted these bus routes operate as bridging services.
BRIDGING_BUS_LOOKUP: dict[str, dict] = {
    "KJ": {
        "routes":      ["T789", "B102", "B106", "Rapid Bus KL"],
        "corridor":    "Kelana Jaya – Shah Alam corridor",
        "pickup_note": "Bridging buses depart from Kelana Jaya, Subang Jaya, "
                       "and Asia Jaya stations. Check @AskRapidKL on X/Twitter "
                       "for live pickup points and schedules.",
    },
    "AG": {
        "routes":      ["T810", "T812", "U84"],
        "corridor":    "Ampang – Chan Sow Lin corridor",
        "pickup_note": "Buses operate from Chan Sow Lin, Cempaka, and Ampang "
                       "Point. Frequency increases during disruptions.",
    },
    "PH": {
        "routes":      ["T811", "T813", "U80"],
        "corridor":    "Sri Petaling – Putra Heights corridor",
        "pickup_note": "Bridging buses from Sri Petaling, Bukit Jalil, and "
                       "Putra Heights. Allow 15–30 min extra travel time.",
    },
    "KGL": {
        "routes":      ["T789", "T814", "Rapid Bus MRT Feeder"],
        "corridor":    "MRT Kajang – Sungai Buloh corridor",
        "pickup_note": "Feeder buses from Kajang, Bangi, Cheras, and "
                       "Sungai Buloh MRT stations.",
    },
    "PYL": {
        "routes":      ["T807", "T808", "MRT Feeder PY"],
        "corridor":    "MRT Putrajaya – Kwasa Damansara corridor",
        "pickup_note": "Buses from Kwasa Damansara, Cyberjaya, and "
                       "Putrajaya Sentral interchange.",
    },
    "MR": {
        "routes":      ["T502", "T503", "Rapid Bus City"],
        "corridor":    "KL City Centre Monorail corridor",
        "pickup_note": "LRT and MRT stations are within short walking distance "
                       "of most Monorail stations. Walking is often the fastest "
                       "alternative for short trips.",
    },
    "BRT": {
        "routes":      ["SJ01", "SJ02", "Sunway Feeder"],
        "corridor":    "Sunway – USJ corridor",
        "pickup_note": "Limited bus coverage in this corridor. "
                       "E-hailing (Grab / AirAsia MOVE) is the recommended "
                       "primary alternative.",
    },
}

# Walking speed assumption: 80 m/min (~4.8 km/h)
WALK_SPEED_M_PER_MIN = 80.0
# Maximum walking distance to suggest as alternative (metres)
WALK_MAX_M = 1_500


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two GPS coordinates."""
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _parse_gtfs_time(t: str) -> int:
    """GTFS H:MM:SS (hours may exceed 23 for after-midnight service)
    -> seconds since service start. datetime.strptime cannot parse >23h."""
    h, m, sec = t.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + int(sec)


def _walkable_nearby(
    origin_id: str,
    stops: dict,
    exclude_lines: list[str] | None = None,
    max_m: float = WALK_MAX_M,
) -> list[dict]:
    """
    Return stations within walking distance of origin on *different* lines.
    Useful when the user's current line is disrupted.
    """
    if origin_id not in stops:
        return []
    origin = stops[origin_id]
    excl   = set(exclude_lines or [])
    seen_names: set[str] = set()
    results: list[dict]  = []

    for sid, info in stops.items():
        if sid == origin_id:
            continue
        if info.get("route_id") in excl:
            continue
        if info["name"] in seen_names:
            continue  # already have this interchange station
        dist = _haversine_m(origin["lat"], origin["lon"], info["lat"], info["lon"])
        if dist <= max_m:
            seen_names.add(info["name"])
            results.append({
                "name":         info["name"],
                "line":         info.get("route_id", "?"),
                "distance_m":   round(dist),
                "walk_minutes": round(dist / WALK_SPEED_M_PER_MIN),
                "lat":          info["lat"],
                "lon":          info["lon"],
            })

    results.sort(key=lambda x: x["distance_m"])
    return results[:5]


def _ehailing_suggestion(
    origin_id: str,
    dest_id: str,
    stops: dict,
    reason: str = "",
) -> dict:
    """
    Generate an e-hailing (Grab / AirAsia MOVE) suggestion with a fare estimate.
    Fare estimate: RM 3 base + RM 1.80/km (approximate Grab economy rate in KL).
    """
    try:
        o, d = stops[origin_id], stops[dest_id]
        dist_km = _haversine_m(o["lat"], o["lon"], d["lat"], d["lon"]) / 1000
        low  = round(3 + dist_km * 1.5,  0)
        high = round(3 + dist_km * 2.2,  0)
        # Grab AppsFlyer OneLink — routes users into the Grab app on phone
        # (via grab://open?screenType=BOOKING once they tap "Book a ride" on the
        # landing page) or to the download page if not installed. Pre-fill of
        # pickup/destination is not available on the public URL scheme.
        grab_url = (
            "https://www.grab.com/my/download/"
            "?af_adset=grab_website&c=organic_web"
            "&af_dp=grab%3A%2F%2Fopen%3FscreenType%3DBOOKING"
            "&af_ad=/my/transport/&af_channel=transport"
            "&is_retargeting=true&af_js_web=true&pid=organic_web"
            "&af_ss_ver=2_7_3&af_sub1=book_ride"
        )
        # Also expose a Google Maps deep link as a secondary option.
        maps_url = (
            f"https://www.google.com/maps/dir/?api=1"
            f"&origin={o['lat']},{o['lon']}"
            f"&destination={d['lat']},{d['lon']}"
            f"&travelmode=driving"
        )
    except Exception:
        dist_km, low, high = 0, 5, 20
        grab_url = (
            "https://www.grab.com/my/download/"
            "?af_adset=grab_website&c=organic_web"
            "&af_dp=grab%3A%2F%2Fopen%3FscreenType%3DBOOKING"
            "&af_ad=/my/transport/&af_channel=transport"
            "&is_retargeting=true&af_js_web=true&pid=organic_web"
            "&af_ss_ver=2_7_3&af_sub1=book_ride"
        )
        maps_url = "https://www.google.com/maps"

    return {
        "recommended":    True,
        "reason":         reason or "Alternative to disrupted rail service",
        "distance_km":    round(dist_km, 1),
        "fare_estimate":  f"RM {int(low)} - {int(high)}",
        "services":       ["Grab", "AirAsia MOVE", "MyCar"],
        "grab_url":       grab_url,
        "maps_url":       maps_url,
    }


DEFAULT_PREFERENCES: dict = {
    "priority":            "fastest",  # "fastest" | "fewest_stops" | "fewest_transfers"
    "prefer_shelter":      False,
    "avoid_lines":         [],         # list of route_ids to exclude
    "require_wheelchair":  False,      # step-free / OKU: exclude inaccessible stations
    "prefer_less_walking": False,      # penalise on-foot transfers (soft preference)
    "require_tactile":     False,      # blind: warn about stations w/o tactile-to-outside
    "prefer_quiet":        False,      # prefer historically less-crowded segments
    "max_walk_minutes":    0,          # hard cap on total walking (0 = no limit; e.g. 5/10/15)
    "prefer_safer_walk":   False,      # warn about the walking approach at either endpoint
}

_graph: nx.Graph | None = None
_stops: dict[str, dict] = {}
_stop_sequence: dict[str, list[str]] = {}  # route_id -> ordered list of stop_ids


def _load_gtfs() -> tuple[dict, dict]:
    access = _load_accessibility()
    stops = {}
    with open(GTFS_DIR / "stops.txt", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # 2026 feed quirk: Kajang-line stops carry route_id "MRT" — normalize to KGL
            rid = "KGL" if row["route_id"] == "MRT" else row["route_id"]
            sid = row["stop_id"]
            acc = access.get(sid.upper()) or {}
            stops[sid] = {
                "name": row["stop_name"],
                "lat": float(row["stop_lat"]),
                "lon": float(row["stop_lon"]),
                "route_id": rid,
                "category": row["category"],
                # True / False / None(unverified) from the manual accessibility overlay
                "wheelchair": acc.get("wheelchair"),
                "tactile":    acc.get("tactile"),
            }

    # Build ordered stop sequences per trip, keeping scheduled arrival times.
    # NOTE: utf-8-sig — the file carries a BOM, and its route_id column uses
    # short names (AGL/KJL/...) that do NOT match canonical route ids; the
    # join must go through trip_id -> trips.txt.
    trip_stops: dict[str, list[tuple[int, str, int]]] = {}
    with open(GTFS_DIR / "stop_times.txt", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            trip_id = row["trip_id"]
            seq = int(row["stop_sequence"])
            stop_id = row["stop_id"]
            arr = _parse_gtfs_time(row["arrival_time"])
            trip_stops.setdefault(trip_id, []).append((seq, stop_id, arr))

    # Map trip_id -> route_id
    trip_routes: dict[str, str] = {}
    with open(GTFS_DIR / "trips.txt", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            trip_routes[row["trip_id"]] = row["route_id"]

    # Build route -> ordered stops (deduplicate, use first trip per route),
    # and real per-edge travel minutes from consecutive scheduled arrivals.
    route_stop_seq: dict[str, list[str]] = {}
    edge_minutes: dict[tuple[str, str], float] = {}
    for trip_id, seq_stops in trip_stops.items():
        route_id = trip_routes.get(trip_id)
        if route_id and route_id not in route_stop_seq:
            ordered = sorted(seq_stops)
            route_stop_seq[route_id] = [sid for _, sid, _ in ordered]
            for (_, s1, t1), (_, s2, t2) in zip(ordered, ordered[1:]):
                mins = max((t2 - t1) / 60.0, 0.5)   # floor: no zero-weight edges
                edge_minutes[(s1, s2)] = mins
                edge_minutes[(s2, s1)] = mins

    # Official line names from routes.txt (route_id -> "LRT Kelana Jaya Line")
    route_names: dict[str, str] = {}
    with open(GTFS_DIR / "routes.txt", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            route_names[row["route_id"]] = row["route_long_name"]

    return stops, route_stop_seq, route_names, edge_minutes


def _build_graph(
    stops: dict,
    route_stop_seq: dict,
    disrupted_stops: list[str] | None = None,
    preferences: dict | None = None,
    edge_minutes: dict | None = None,
) -> nx.Graph:
    G = nx.Graph()
    disrupted  = set(disrupted_stops or [])
    prefs      = {**DEFAULT_PREFERENCES, **(preferences or {})}
    priority   = prefs["priority"]
    shelter    = prefs["prefer_shelter"]
    avoid_set  = set(prefs.get("avoid_lines") or [])
    wheelchair = prefs.get("require_wheelchair", False)
    # A walking cap implies the less-walking bias, so Dijkstra hunts for low-walk
    # routes that can satisfy it.
    less_walk  = prefs.get("prefer_less_walking", False) or int(prefs.get("max_walk_minutes") or 0) > 0
    quiet      = prefs.get("prefer_quiet", False)

    # Step-free routing: stations EXPLICITLY marked not-accessible are removed
    # from the graph, exactly like a disrupted stop, so Dijkstra can never route
    # a wheelchair user through them (including as an interchange). Unverified
    # (None) stations are kept but surfaced as a warning by reroute().
    if wheelchair:
        disrupted = disrupted | {
            sid for sid, info in stops.items() if info.get("wheelchair") is False
        }

    # Penalty multiplier per line when shelter mode is on
    interchange_w = INTERCHANGE_PENALTY
    if priority == "fewest_transfers":
        interchange_w = 30   # strongly discourage transfers
    elif priority == "fewest_stops":
        interchange_w = 0.5  # tie-breaker only — never trade extra stops for fewer transfers

    # Add all stops as nodes
    for stop_id, info in stops.items():
        if stop_id not in disrupted:
            G.add_node(stop_id, **info)

    # Add edges along each route. Weight is computed PER EDGE: real scheduled
    # minutes from stop_times.txt when available, constants only as fallback.
    em = edge_minutes or {}
    for route_id, ordered_stops in route_stop_seq.items():
        if route_id in avoid_set:
            continue  # user wants to skip this line entirely

        for i in range(len(ordered_stops) - 1):
            a, b = ordered_stops[i], ordered_stops[i + 1]
            if a in disrupted or b in disrupted or a not in stops or b not in stops:
                continue
            if priority == "fewest_stops":
                w = 1.0
            else:
                w = em.get((a, b), LINE_TRAVEL_TIME.get(route_id, 3.0))
            if shelter:
                w += SHELTER_PENALTY.get(route_id, 0.0)
            if quiet:
                # Busier legs (historical O-D ridership) cost more, so Dijkstra
                # prefers quieter parallel routes where they exist.
                w += _SEGMENT_BUSYNESS.get("|".join(sorted([a, b])), 0.0) * QUIET_MAX_PENALTY
            G.add_edge(a, b, weight=w, route_id=route_id)

    # Add interchange edges (same station name, different lines)
    name_to_stops: dict[str, list[str]] = {}
    for stop_id, info in stops.items():
        if stop_id not in disrupted:
            name_to_stops.setdefault(info["name"], []).append(stop_id)

    # "prefer_less_walking" makes every on-foot transfer costlier so Dijkstra
    # favours staying on one line / using shorter transfers.
    same_station_w = interchange_w + (WALK_AVERSION_PENALTY if less_walk else 0)

    for name, ids in name_to_stops.items():
        exposed = _norm_station(name) in _EXPOSED_INTERCHANGES
        w_int = same_station_w + (INTERCHANGE_EXPOSED_PENALTY
                                  if (shelter and exposed) else 0)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                # `weight` drives Dijkstra (mode + preference penalties); `disp`
                # is the REAL transfer time used only for the shown estimate, so
                # penalties never corrupt the minutes displayed to the user.
                G.add_edge(ids[i], ids[j], weight=w_int,
                           disp=INTERCHANGE_PENALTY, route_id="INTERCHANGE",
                           exposed=exposed)

    # Named interchange pairs whose station names differ, so the same-name
    # rule above misses them. Weight = linked-bridge walk, slightly above a
    # same-platform transfer.
    for name_a, name_b, walk_min in NAMED_INTERCHANGES:
        ids_a = name_to_stops.get(name_a, [])
        ids_b = name_to_stops.get(name_b, [])
        # exposed if EITHER endpoint name is marked not-covered in the survey CSV
        exposed = bool(_EXPOSED_INTERCHANGES & {_norm_station(name_a), _norm_station(name_b)})
        for a in ids_a:
            for b in ids_b:
                if a == b:
                    continue
                w = max(interchange_w, walk_min)
                # Out-of-station walks hurt more under prefer_less_walking:
                # add the walk length again so a 12-min street walk is heavily
                # deprioritised versus a same-platform change.
                if less_walk:
                    w += walk_min
                # prefer_shelter: an EXPOSED transfer (survey: not covered) is
                # penalised so Dijkstra prefers a route whose transfers stay dry.
                if shelter and exposed:
                    w += INTERCHANGE_EXPOSED_PENALTY
                # add_edge overwrites any same-name edge created above,
                # so walk transfers replace the default 5-min weight. `disp`
                # keeps the REAL walk minutes for the displayed estimate.
                G.add_edge(a, b, weight=w, disp=walk_min, route_id="INTERCHANGE",
                           exposed=exposed)

    return G


FUZZY_SCORE_CUTOFF = 74  # WRatio below this = no confident match


def _find_stop_id(query: str, stops: dict) -> tuple[str | None, str | None]:
    """
    Resolve a user-typed station name to a stop_id.
    Returns (stop_id, matched_name); matched_name differs from the raw query
    when fuzzy correction was applied.
    """
    q = query.upper().strip()
    if not q:
        return None, None

    # 0. Common aliases / initialisms commuters use that don't appear in GTFS
    #    (e.g. "TRX" for Tun Razak Exchange). Resolved BEFORE geocoding so they
    #    work offline and pick the same platform every time — a bare "TRX" must
    #    behave identically to typing the full station name.
    q = _STATION_ALIASES.get(q, q)

    # 1. Exact match
    for stop_id, info in stops.items():
        if info["name"].upper().strip() == q:
            return stop_id, info["name"]

    # 2. Substring match (kept for backwards compatibility)
    for stop_id, info in stops.items():
        if q in info["name"].upper():
            return stop_id, info["name"]

    # 3. Fuzzy match (typo tolerance, e.g. "puchung prima" -> PUCHONG PRIMA)
    name_to_id: dict[str, str] = {}
    for stop_id, info in stops.items():
        name_to_id.setdefault(info["name"].upper(), stop_id)
    match = process.extractOne(
        q, list(name_to_id.keys()),
        scorer=fuzz.WRatio, score_cutoff=FUZZY_SCORE_CUTOFF,
    )
    if match:
        return name_to_id[match[0]], match[0]

    return None, None


def _suggest_names(query: str, stops: dict, n: int = 3) -> list[str]:
    """Top-n closest station names for a failed lookup ('did you mean...')."""
    names = list({info["name"] for info in stops.values()})
    return [m[0] for m in process.extract(
        query.upper().strip(), names, scorer=fuzz.WRatio, limit=n)]


_geocode_cache: dict[str, tuple[float, float, str] | None] = {}

# Klang Valley bounding box (lon_left, lat_top, lon_right, lat_bottom)
_KLANG_VALLEY_VIEWBOX = "101.15,3.45,101.98,2.80"
# Beyond this, "nearest station" stops being useful advice
PLACE_MAX_STATION_M = 5_000


def _geocode_place(query: str) -> tuple[float, float, str] | None:
    """Resolve a free-text place (mall, landmark) to lat/lon via Nominatim
    (OpenStreetMap). Free, no key; bounded to the Klang Valley. Returns
    (lat, lon, display_name) or None. Never raises."""
    key = query.strip().lower()
    if key in _geocode_cache:
        return _geocode_cache[key]
    try:
        import json as _json
        import urllib.parse
        import urllib.request
        url = (
            "https://nominatim.openstreetmap.org/search?format=json&limit=1"
            f"&viewbox={_KLANG_VALLEY_VIEWBOX}&bounded=1"
            f"&q={urllib.parse.quote(query)}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "LRT-Companion-FYP/1.0 (student project)"})
        with urllib.request.urlopen(req, timeout=5) as r:
            rows = _json.loads(r.read().decode("utf-8"))
        if rows:
            hit = rows[0]
            result = (float(hit["lat"]), float(hit["lon"]), hit.get("display_name", query).split(",")[0])
        else:
            # Fallback: Photon (OSM autocomplete engine) handles PARTIAL names
            # like "sunway pyram" that Nominatim's full-text search misses.
            purl = (
                "https://photon.komoot.io/api/?limit=1"
                "&lat=3.10&lon=101.60"   # bias toward Klang Valley centre
                f"&q={urllib.parse.quote(query)}"
            )
            preq = urllib.request.Request(purl, headers={"User-Agent": "LRT-Companion-FYP/1.0 (student project)"})
            with urllib.request.urlopen(preq, timeout=5) as r:
                feats = _json.loads(r.read().decode("utf-8")).get("features", [])
            result = None
            if feats:
                lon, lat = feats[0]["geometry"]["coordinates"]
                # accept only hits actually inside the Klang Valley box
                if 2.80 <= lat <= 3.45 and 101.15 <= lon <= 101.98:
                    name = feats[0]["properties"].get("name", query)
                    result = (float(lat), float(lon), name)
    except Exception:
        result = None
    _geocode_cache[key] = result
    return result


def _nearest_station(lat: float, lon: float, stops: dict) -> tuple[str, float]:
    """Closest station to a coordinate. Returns (stop_id, distance_m)."""
    best_id, best_d = "", float("inf")
    for sid, info in stops.items():
        d = _haversine_m(lat, lon, info["lat"], info["lon"])
        if d < best_d:
            best_id, best_d = sid, d
    return best_id, best_d


def _resolve_endpoint(query: str, stops: dict) -> tuple[str | None, dict | None]:
    """Station lookup with place-geocoding fallback.
    Returns (stop_id, place_note). place_note is set when the query was a
    non-station place resolved to its nearest station."""
    stop_id, _ = _find_stop_id(query, stops)
    if stop_id:
        return stop_id, None
    geo = _geocode_place(query)
    if not geo:
        return None, None
    lat, lon, place_name = geo
    sid, dist = _nearest_station(lat, lon, stops)
    if not sid or dist > PLACE_MAX_STATION_M:
        return None, None
    return sid, {
        "query":      query,
        "place":      place_name,
        "lat":        lat,
        "lon":        lon,
        "station":    stops[sid]["name"],
        "distance_m": round(dist),
        "walk_minutes": round(dist / WALK_SPEED_M_PER_MIN),
    }


def _build_instructions(segments: list[dict], route_names: dict) -> list[str]:
    """Turn route segments into short plain-language steps (elder-friendly)."""
    steps: list[str] = []
    for i, seg in enumerate(segments):
        line = route_names.get(seg["line"], seg["line"])
        n = seg["n_stops"]
        steps.append(
            f"Board the {line} at {seg['from']} and ride "
            f"{n} stop{'s' if n != 1 else ''} to {seg['to']} (about {seg['minutes']} min)."
        )
        if i < len(segments) - 1:
            nxt = segments[i + 1]
            nxt_line = route_names.get(nxt["line"], nxt["line"])
            if nxt["from"] == seg["to"]:
                steps.append(f"At {seg['to']}, change to the {nxt_line} platform.")
            else:
                steps.append(f"At {seg['to']}, exit and walk to {nxt['from']} for the {nxt_line}.")
    if segments:
        steps.append(f"You have arrived at {segments[-1]['to']}.")
    return steps


def _describe_path(path: list[str], G: "nx.Graph", stops: dict,
                   edge_minutes: dict, route_names: dict) -> dict:
    """Describe one node path: segments, steps, totals, and instructions."""
    segments: list[dict] = []
    current_line = None
    seg_ids: list[str] = []
    for i in range(len(path) - 1):
        edge = G[path[i]][path[i + 1]]
        line = edge.get("route_id", "UNKNOWN")
        if line != current_line:
            if current_line is not None and current_line != "INTERCHANGE":
                segments.append(_build_segment(current_line, seg_ids, stops, edge_minutes))
            current_line = line
            seg_ids = [path[i]]
        seg_ids.append(path[i + 1])
    if current_line and current_line != "INTERCHANGE":
        segments.append(_build_segment(current_line, seg_ids, stops, edge_minutes))

    # Display minutes must stay honest regardless of the mode's edge weights
    # (fewest_stops weighs edges at 1.0, fewest_transfers inflates interchanges
    # to 30) — so recompute: real segment minutes + real transfer walk time,
    # capping distorted interchange weights at a plausible 12-min walk.
    ride_min = sum(seg["minutes"] for seg in segments)
    transfer_min = sum(
        # `disp` = real transfer minutes (unaffected by mode/preference
        # penalties); fall back to the capped weight for older edges.
        G[path[i]][path[i + 1]].get("disp",
            min(G[path[i]][path[i + 1]]["weight"], 12.0))
        for i in range(len(path) - 1)
        if G[path[i]][path[i + 1]].get("route_id") == "INTERCHANGE"
    )
    # Interchange stations on this path whose transfer walk is open-air (exposed
    # to weather) — used to warn shelter-seeking users to bring an umbrella.
    exposed_transfers = [
        stops[path[i]]["name"].strip()
        for i in range(len(path) - 1)
        if G[path[i]][path[i + 1]].get("route_id") == "INTERCHANGE"
        and G[path[i]][path[i + 1]].get("exposed")
        and path[i] in stops
    ]
    return {
        "segments":          segments,
        "steps":             [{"from": s["from"], "to": s["to"], "line": s["line"]} for s in segments],
        "total_stops":       len(path) - 1,
        "estimated_minutes": round(ride_min + transfer_min),
        "transfer_minutes":  round(transfer_min),   # walking/transfer time between lines
        "interchanges":      max(len(segments) - 1, 0),
        "lines_used":        [s["line"] for s in segments],
        "exposed_transfers": exposed_transfers,
        "instructions":      _build_instructions(segments, route_names),
    }


def reroute(
    origin: str,
    destination: str,
    disrupted_stops: list[str] | None = None,
    preferences: dict | None = None,
) -> dict:
    """
    Find the best route from origin to destination,
    avoiding disrupted stops, respecting user preferences.

    Args:
        origin:          Station name (e.g. "KLCC")
        destination:     Station name (e.g. "PUTRA HEIGHTS")
        disrupted_stops: List of stop_ids to remove from the graph
        preferences:     Dict with keys:
                           priority       – "fastest" | "fewest_stops" | "fewest_transfers"
                           prefer_shelter – bool (adds cost to exposed BRT / Monorail)
                           avoid_lines    – list of route_ids to exclude

    Returns:
        route info with stations, lines, estimated time
    """
    stops, route_stop_seq, route_names, edge_minutes = _load_gtfs()

    # GTFS stop_ids are uppercase — normalise so "mr8" blocks MR8 instead of
    # silently blocking nothing while still being reported as avoided.
    # Station NAMES are accepted too ("bukit nanas" → MR8; interchanges block
    # every platform). Exact-name only — fuzzy matching is too risky for
    # something that removes stations from the network.
    resolved: list[str] = []
    unresolved: list[str] = []
    for tok in (disrupted_stops or []):
        tok = (tok or "").strip().upper()
        if not tok:
            continue
        if tok in stops:
            resolved.append(tok)
            continue
        named = [sid for sid, s in stops.items()
                 if s["name"] == tok or s["name"].startswith(tok + " - ")]
        if named:
            resolved.extend(named)
        else:
            # Never silently "avoid" something that doesn't exist — report it
            unresolved.append(tok)
    disrupted_stops = resolved or None

    origin_id, origin_place = _resolve_endpoint(origin, stops)
    dest_id,   dest_place   = _resolve_endpoint(destination, stops)

    if not origin_id:
        return {"error": f"Station or place not found: {origin}",
                "bad_field": "origin",
                "suggestions": _suggest_names(origin, stops)}
    if not dest_id:
        return {"error": f"Station or place not found: {destination}",
                "bad_field": "destination",
                "suggestions": _suggest_names(destination, stops)}

    # Step-free routing: if the trip's own endpoints are marked not-accessible,
    # say so plainly rather than letting them fail later as a generic "no route".
    require_wc = {**DEFAULT_PREFERENCES, **(preferences or {})}.get("require_wheelchair", False)
    if require_wc:
        # If the resolved platform is inaccessible but the SAME station has an
        # accessible platform (e.g. KL Sentral: Monorail no, LRT yes), switch to
        # it instead of blocking the whole interchange.
        if stops[origin_id].get("wheelchair") is False:
            alt = _accessible_sibling(origin_id, origin, stops)
            if alt:
                origin_id = alt
            else:
                return {"error": f"{stops[origin_id]['name']} is not wheelchair-accessible.",
                        "bad_field": "origin", "accessibility": True}
        if stops[dest_id].get("wheelchair") is False:
            alt = _accessible_sibling(dest_id, destination, stops)
            if alt:
                dest_id = alt
            else:
                return {"error": f"{stops[dest_id]['name']} is not wheelchair-accessible.",
                        "bad_field": "destination", "accessibility": True}

    G = _build_graph(stops, route_stop_seq, disrupted_stops, preferences, edge_minutes)

    if origin_id not in G:
        return {"error": f"Origin station '{origin}' is in a disrupted zone."}
    if dest_id not in G:
        return {"error": f"Destination station '{destination}' is in a disrupted zone."}

    try:
        from itertools import islice
        # Up to 3 meaningfully-different alternatives. The generator can emit
        # many cosmetic variants (same lines, different interchange node), so
        # cap candidates and dedupe on the line sequence.
        K, MAX_CANDIDATES = 3, 10
        routes: list[dict] = []
        seen_line_seqs: set[tuple] = set()
        for path in islice(
            nx.shortest_simple_paths(G, origin_id, dest_id, weight="weight"),
            MAX_CANDIDATES,
        ):
            desc = _describe_path(path, G, stops, edge_minutes, route_names)
            key = tuple(desc["lines_used"])
            if key in seen_line_seqs:
                continue
            seen_line_seqs.add(key)
            routes.append(desc)
            if len(routes) == K:
                break
        if not routes:
            raise nx.NetworkXNoPath(origin_id, dest_id)
        # Alternatives costing far more than the best are still offered — some
        # riders prefer a guaranteed-but-slower option (feature survey L9:
        # 86% agree) — but flagged and ranked last so the UI can label them.
        fast = [r for r in routes[1:]
                if r["estimated_minutes"] - routes[0]["estimated_minutes"] <= 20]
        slow = [r for r in routes[1:]
                if r["estimated_minutes"] - routes[0]["estimated_minutes"] > 20]
        for r in slow:
            r["slow_option"] = True
        routes = [routes[0]] + fast + slow

        # The ORIGINAL route through the disruption is demoted, not hidden:
        # it stays as the LAST option, flagged, so riders can still judge it
        # (a "disrupted" station may be crowded rather than closed). The
        # detour stays first.
        if disrupted_stops:
            normal = reroute(origin, destination, None, preferences)
            if "error" not in normal:
                normal_ids = {p["stop_id"] for seg in normal["segments"]
                              for p in seg["station_points"]}
                if normal_ids & set(disrupted_stops):
                    through = {k: normal[k] for k in
                               ("segments", "steps", "total_stops",
                                "estimated_minutes", "interchanges",
                                "lines_used", "instructions")}
                    through["through_disruption"] = True
                    routes.append(through)
    except nx.NetworkXNoPath:
        # No rail path — still provide multi-modal alternatives
        disrupted_lines = set()
        for sid in (disrupted_stops or []):
            if sid in stops:
                disrupted_lines.add(stops[sid].get("route_id", ""))
        # If the dead-end was caused by the user's own preferences (e.g. an
        # avoided line was the only path), recommend the unconstrained route.
        relaxed = None
        applied_prefs = {**DEFAULT_PREFERENCES, **(preferences or {})}
        constrained = (
            applied_prefs["priority"] != "fastest"
            or applied_prefs["prefer_shelter"]
            or bool(applied_prefs.get("avoid_lines"))
            or applied_prefs.get("prefer_less_walking")
            or applied_prefs.get("prefer_quiet")
            or int(applied_prefs.get("max_walk_minutes") or 0) > 0
        )
        if constrained:
            base = reroute(origin, destination, disrupted_stops, None)
            if "error" not in base:
                relaxed = base
        return {
            "error": "No rail route found between these stations with current disruptions.",
            "preference_note": (
                {"reason": "no_route_with_preferences",
                 "message": "No route matches your preferences — but a route exists without them.",
                 "relaxed_minutes": relaxed["estimated_minutes"]} if relaxed else None
            ),
            "relaxed_route": relaxed,
            "alternatives": {
                "bridging_buses": [
                    {**BRIDGING_BUS_LOOKUP[line], "line": line}
                    for line in disrupted_lines if line in BRIDGING_BUS_LOOKUP
                ],
                "walkable_nearby": _walkable_nearby(origin_id, stops),
                "ehailing": _ehailing_suggestion(
                    origin_id, dest_id, stops,
                    reason="No rail route available — e-hailing is recommended.",
                ),
            },
        }

    best = routes[0]

    applied = {**DEFAULT_PREFERENCES, **(preferences or {})}

    # ── Multi-modal alternatives ───────────────────────────────────────────────
    disrupted_lines = set()
    for sid in (disrupted_stops or []):
        if sid in stops:
            disrupted_lines.add(stops[sid].get("route_id", ""))

    # Bridging buses for each disrupted line
    bridging = [
        {**BRIDGING_BUS_LOOKUP[line], "line": line}
        for line in disrupted_lines
        if line in BRIDGING_BUS_LOOKUP
    ]

    # Walkable stations near origin on OTHER lines (walking to a station on
    # the line you are already boarding is never useful advice)
    origin_line = stops[origin_id].get("route_id", "")
    walkable = _walkable_nearby(
        origin_id, stops,
        exclude_lines=list(disrupted_lines | {origin_line}),
    )

    # E-hailing — always include, priority elevated when disruption present
    ehailing = _ehailing_suggestion(
        origin_id, dest_id, stops,
        reason=(
            "Disruption detected on route — e-hailing offers a direct door-to-door alternative."
            if disrupted_stops else
            "Direct alternative to avoid rail transfers."
        ),
    )

    place_notes = []
    if origin_place:
        place_notes.append({**origin_place, "field": "origin"})
        d = origin_place["distance_m"]
        approach = (
            f"From {origin_place['place']}, walk about {origin_place['walk_minutes']} min "
            f"({d} m) to {stops[origin_id]['name']} station."
            if d <= 1500 else
            f"From {origin_place['place']}, take a short ride (~{round(d/1000, 1)} km) "
            f"to {stops[origin_id]['name']} station."
        )
        for r in routes:
            r["instructions"].insert(0, approach)
    if dest_place:
        place_notes.append({**dest_place, "field": "destination"})
        d = dest_place["distance_m"]
        tail = (
            f"{dest_place['place']} is about {d} m from {stops[dest_id]['name']} station"
            + (f" ({dest_place['walk_minutes']} min walk)." if d <= 1500 else " — consider a short ride.")
        )
        for r in routes:
            r["instructions"].append(tail)

    # ── Walking awareness ──────────────────────────────────────────────────────
    # Total on-foot time = line-transfer walking + walking to/from the stations
    # when origin/destination are places (not stations). Rides ( > 1.5 km ) are
    # not counted as walking. Surfaced per route + a reminder when it's heavy.
    access_walk = 0
    if origin_place and origin_place.get("distance_m", 99999) <= 1500:
        access_walk += origin_place.get("walk_minutes", 0)
    if dest_place and dest_place.get("distance_m", 99999) <= 1500:
        access_walk += dest_place.get("walk_minutes", 0)
    for r in routes:
        r["walk_minutes"] = r.get("transfer_minutes", 0) + access_walk

    # Max-walking cap: keep only routes within the user's limit; if none fit,
    # keep the lowest-walk route and flag that the limit couldn't be met.
    cap = int(applied.get("max_walk_minutes") or 0)
    over_cap_note = None
    if cap > 0:
        within = [r for r in routes if r.get("walk_minutes", 0) <= cap]
        if within:
            routes[:] = within
        else:
            routes.sort(key=lambda r: r.get("walk_minutes", 0))
            over_cap_note = (
                f"No route stays within ~{cap} min of walking — the least is "
                f"~{routes[0].get('walk_minutes', 0)} min."
            )
        best = routes[0]

    walking_note = None
    if over_cap_note:
        walking_note = {"minutes": best.get("walk_minutes", 0), "reason": "over_cap",
                        "message": over_cap_note}
    elif best.get("walk_minutes", 0) >= WALK_WARN_MINUTES:
        walking_note = {
            "minutes": best["walk_minutes"],
            "message": (
                f"Heads up — this route involves about {best['walk_minutes']} min of walking "
                f"(line transfers plus getting to and from stations). "
                f"If that's a lot for you, check the other options below or consider e-hailing."
            ),
        }

    # Preference relaxation: if the user's preferences cost >= 10 min vs the
    # unconstrained fastest route, surface that trade-off with a recommendation.
    preference_note = None
    relaxed_route = None
    constrained = (
        applied["priority"] != "fastest"
        or applied["prefer_shelter"]
        or bool(applied.get("avoid_lines"))
        or applied.get("prefer_less_walking")
        or applied.get("prefer_quiet")
        or int(applied.get("max_walk_minutes") or 0) > 0
    )
    if constrained:
        base = reroute(origin, destination, disrupted_stops, None)
        if "error" not in base:
            same_route = (
                base.get("lines_used") == best.get("lines_used")
                and base.get("total_stops") == best.get("total_stops")
            )
            diff = best["estimated_minutes"] - base["estimated_minutes"]
            if same_route:
                # Honest feedback: the toggle IS applied — distinguish "route already
                # complies" from "no compliant alternative exists".
                uses_exposed = applied["prefer_shelter"] and any(
                    ln in SHELTER_PENALTY for ln in best.get("lines_used", []))
                preference_note = {
                    "reason": "already_satisfied",
                    "message": (
                        "No fully sheltered alternative exists for this trip — this remains the best route."
                        if uses_exposed else
                        "Your preferences are active — the fastest route already satisfies them, so no detour was needed."
                    ),
                }
            elif diff >= 10:
                relaxed_route = base
                preference_note = {
                    "reason": "faster_without_preferences",
                    "message": (
                        f"Your preferences add about {diff} min to this trip. "
                        f"Without them it takes {base['estimated_minutes']} min."
                    ),
                    "relaxed_minutes": base["estimated_minutes"],
                }
            else:
                preference_note = {
                    "reason": "rerouted_for_preferences",
                    "message": (
                        f"Route adjusted to match your preferences"
                        + (f" (+{diff} min vs the unconstrained fastest)." if diff > 0 else " at no extra travel time.")
                    ),
                }

    # Step-free honesty: stations on the chosen route with NO verified
    # accessibility data (None). We route through them (nothing says they're
    # unusable) but flag them so the user isn't given false assurance.
    wheelchair_note = None
    if applied.get("require_wheelchair"):
        unverified = []
        seen = set()
        for seg in best.get("segments", []):
            for p in seg.get("station_points", []):
                sid = p.get("stop_id")
                if sid in stops and stops[sid].get("wheelchair") is None and p["name"] not in seen:
                    seen.add(p["name"])
                    unverified.append(p["name"])
        if unverified:
            wheelchair_note = {
                "reason": "unverified_stations",
                "message": ("Accessibility is not yet verified for: "
                            + ", ".join(unverified)
                            + ". These are included but not confirmed step-free."),
                "stations": unverified,
            }

    # Blind / tactile guidance: a visually-impaired user can physically pass
    # through any station, so we do NOT exclude stations (that would sever whole
    # lines). Instead we WARN when the route uses stations whose tactile guiding
    # path does not reach outside the station.
    tactile_note = None
    if applied.get("require_tactile"):
        no_tactile = []
        seen = set()
        for seg in best.get("segments", []):
            for p in seg.get("station_points", []):
                sid = p.get("stop_id")
                if sid in stops and stops[sid].get("tactile") is False and p["name"] not in seen:
                    seen.add(p["name"])
                    no_tactile.append(p["name"])
        if no_tactile:
            tactile_note = {
                "reason": "no_tactile_path",
                "message": ("Tactile guiding paths may not extend outside these stations: "
                            + ", ".join(no_tactile)
                            + ". Consider requesting staff assistance at these stations."),
                "stations": no_tactile,
            }

    # Shelter warning: if the shelter-seeking user's best route still contains an
    # open-air interchange walk (no fully covered alternative), tell them so they
    # can bring an umbrella — honest, like the walking/tactile notes.
    shelter_note = None
    if applied.get("prefer_shelter") and best.get("exposed_transfers"):
        exposed = best["exposed_transfers"]
        shelter_note = {
            "reason": "exposed_transfer",
            "message": ("This route includes an open-air transfer walk at "
                        + ", ".join(exposed)
                        + " — bring an umbrella if it's raining. No fully covered "
                        "alternative was available for this trip."),
            "stations": exposed,
        }

    # Walk-safety warning: the rail route itself is unchanged (you board and
    # alight where you asked), so this is purely advisory about the on-foot
    # approach at each endpoint. Opt-in via prefer_safer_walk.
    safety_note = _build_safety_note(
        applied, stops[origin_id]["name"], stops[dest_id]["name"])

    return {
        "origin":                  stops[origin_id]["name"],
        "destination":             stops[dest_id]["name"],
        **best,                    # segments/steps/totals/instructions of the best route
        "routes":                  routes,
        "place_notes":             place_notes,
        "wheelchair_note":         wheelchair_note,
        "tactile_note":            tactile_note,
        "shelter_note":            shelter_note,
        "safety_note":             safety_note,
        "query_corrected": (
            origin.upper().strip() != stops[origin_id]["name"].upper()
            or destination.upper().strip() != stops[dest_id]["name"].upper()
        ),
        "preference_note":         preference_note,
        "relaxed_route":           relaxed_route,
        "walking_note":            walking_note,
        "disrupted_stops_avoided": disrupted_stops or [],
        "disrupted_unresolved":    unresolved,
        # Coordinates of the avoided stations so the map can SHOW what the
        # route is detouring around (deduped by name — one marker per station)
        "disrupted_points": [
            {"stop_id": sid, "name": stops[sid]["name"],
             "lat": stops[sid]["lat"], "lon": stops[sid]["lon"]}
            for i, sid in enumerate(disrupted_stops or [])
            if sid in stops
            and stops[sid]["name"] not in
                {stops[p]["name"] for p in (disrupted_stops or [])[:i] if p in stops}
        ],
        "preferences_applied":     applied,
        "alternatives": {
            "bridging_buses": bridging,
            "walkable_nearby": walkable,
            "ehailing":        ehailing,
        },
    }


def _build_safety_note(applied: dict, origin_name: str,
                       dest_name: str) -> dict | None:
    """Advisory note about the walking approach at the origin/destination.

    Returns None unless prefer_safer_walk is on AND at least one endpoint scored
    below `good` in the survey. Never alters routing — the walk happens at fixed
    endpoints, so there is nothing to route around; the honest response is to
    tell the user what to expect. See _load_walk_safety for why the underlying
    data is advisory rather than authoritative.
    """
    if not applied.get("prefer_safer_walk"):
        return None

    flagged = []
    for role, name in (("origin", origin_name), ("destination", dest_name)):
        entry = _WALK_SAFETY.get(_norm_station(name))
        if entry and entry["level"] != "good":
            flagged.append({"role": role, "station": name, **entry})
    if not flagged:
        return None

    parts = [f"{f['station']} ({f['role']}): " + ", ".join(f["failing"])
             for f in flagged]
    worst = "bad" if any(f["level"] == "bad" for f in flagged) else "medium"
    return {
        "reason":   "walk_safety",
        "level":    worst,
        "message":  ("Walking approach to watch: " + "; ".join(parts)
                     + ". Based on a Street View survey of the 100-200 m around "
                       "each station — an observational estimate, not a "
                       "guarantee, and conditions may have changed."),
        "stations": flagged,
    }


def _build_segment(
    line: str,
    station_ids: list[str],
    stops: dict,
    travel_times: dict,
) -> dict:
    """Turn a list of stop IDs on one line into a rich segment dict."""
    station_names  = [stops[sid]["name"] for sid in station_ids if sid in stops]
    station_points = [
        {
            "name": stops[sid]["name"],
            "lat":  stops[sid]["lat"],
            "lon":  stops[sid]["lon"],
            "stop_id": sid,
        }
        for sid in station_ids if sid in stops
    ]
    n_stops = len(station_ids) - 1
    keys_are_pairs = bool(travel_times) and isinstance(next(iter(travel_times)), tuple)
    if keys_are_pairs:
        # edge_minutes dict: sum actual scheduled minutes along the segment
        mins = round(sum(
            travel_times.get((station_ids[i], station_ids[i + 1]),
                             LINE_TRAVEL_TIME.get(line, 3.0))
            for i in range(n_stops)
        ))
    else:
        mins = round(n_stops * travel_times.get(line, 3.0))
    return {
        "line":           line,
        "from":           station_names[0]  if station_names else "",
        "to":             station_names[-1] if station_names else "",
        "stations":       station_names,        # names only (for text display)
        "station_points": station_points,       # with lat/lon (for map)
        "n_stops":        n_stops,
        "minutes":        mins,
    }
