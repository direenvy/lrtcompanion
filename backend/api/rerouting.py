from fastapi import APIRouter
from pydantic import BaseModel
from agents.rerouting_agent import reroute, _load_gtfs

router = APIRouter(prefix="/api/reroute", tags=["Rerouting"])

# Canonical line display order, name and colour (matches the frontend design).
LINE_DISPLAY = {
    "KJ":  ("LRT Kelana Jaya Line", "#ef4444"),
    "AG":  ("LRT Ampang Line",      "#f97316"),
    "PH":  ("LRT Sri Petaling Line","#ec4899"),
    "KGL": ("MRT Kajang Line",      "#22c55e"),
    "PYL": ("MRT Putrajaya Line",   "#eab308"),
    "MR":  ("KL Monorail Line",     "#84cc16"),
    "BRT": ("BRT Sunway Line",      "#10b981"),
    "SA":  ("LRT Shah Alam Line",   "#38bdf8"),
}


class Preferences(BaseModel):
    priority:            str       = "fastest"  # fastest | fewest_stops | fewest_transfers
    prefer_shelter:      bool      = False
    avoid_lines:         list[str] = []
    require_wheelchair:  bool      = False      # step-free / OKU accessible route
    prefer_less_walking: bool      = False      # penalise on-foot transfers
    require_tactile:     bool      = False      # blind: warn on stations w/o tactile path
    prefer_quiet:        bool      = False      # prefer historically less-crowded segments
    max_walk_minutes:    int       = 0          # hard cap on total walking (0 = no limit)
    prefer_safer_walk:   bool      = False      # warn on low-scoring station walk approaches


class RerouteRequest(BaseModel):
    origin:          str
    destination:     str
    disrupted_stops: list[str]   = []
    preferences:     Preferences = Preferences()


@router.post("/find")
def find_route(request: RerouteRequest):
    """
    Find the best route from origin to destination.
    Supports user preferences: priority mode, shelter preference, line avoidance.
    """
    return reroute(
        origin=request.origin,
        destination=request.destination,
        disrupted_stops=request.disrupted_stops or None,
        preferences=request.preferences.model_dump(),
    )


@router.get("/stations")
def list_stations():
    """Return all available station names for the frontend dropdown.

    Reuses the portable GTFS loader instead of reading the CSV from a
    hardcoded path — the previous absolute Windows path 500'd on the Linux
    host, which silently emptied the station autocomplete in production.
    """
    stops, _, _, _ = _load_gtfs()
    stations = [
        {
            "id":   sid,
            "name": s["name"],
            "line": s["route_id"],
            "lat":  s["lat"],
            "lon":  s["lon"],
        }
        for sid, s in stops.items()
    ]
    return {"stations": stations}


@router.get("/network")
def network_map():
    """Full network: every line with its stations in correct route order and
    coordinates, for the 'View full network map' overlay on Plan Trip.
    Order comes from the GTFS timetable (route_stop_seq), so lines draw as
    continuous polylines rather than a scatter of dots."""
    stops, route_stop_seq, _, _ = _load_gtfs()
    lines = []
    for line_id, (name, color) in LINE_DISPLAY.items():
        ordered = route_stop_seq.get(line_id, [])
        stations = [
            {"stop_id": sid, "name": stops[sid]["name"],
             "lat": stops[sid]["lat"], "lon": stops[sid]["lon"]}
            for sid in ordered if sid in stops
        ]
        if stations:
            lines.append({"line_id": line_id, "name": name,
                          "color": color, "stations": stations})
    total = sum(len(l["stations"]) for l in lines)
    return {"lines": lines, "line_count": len(lines), "station_count": total}
