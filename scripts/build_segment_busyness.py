"""
Build per-segment historical busyness from data.gov.my Rapid Rail O-D ridership.

Source: ridership_od_rapidrail_daily (origin, destination, date, ridership).
Idea:   each O-D pair's passengers ride along their shortest path; add the pair's
        trips to every RIDE segment on that path; sum across all pairs -> how many
        passengers historically load each station-to-station leg. Normalised 0..1.

This is a HISTORICAL, aggregate heuristic (daily totals, no time-of-day). It
estimates which legs are busier on average, NOT live crowding or seat availability.

Output: data/govdata/segment_busyness.json  { "STOPA|STOPB": ratio, ... , "_meta": {...} }
Run:    python scripts/build_segment_busyness.py
"""
import sys, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import pandas as pd
import networkx as nx
from rapidfuzz import process, fuzz
import agents.rerouting_agent as rr

PARQUET = ROOT / "data" / "govdata" / "rapidrail_od_daily.parquet"
OUT     = ROOT / "data" / "govdata" / "segment_busyness.json"

# Parquet station names that don't match GTFS by name (abbreviations / reworded)
NAME_OVERRIDES = {
    "TTDI":                    "KG10",   # Taman Tun Dr Ismail
    "BANDAR TUN HUSSIEN ONN":  "KG29",   # spelling: HUSSIEN -> HUSSEIN
    "BANK RAKYAT BANGSAR":     "KJ16",   # GTFS: "BANGSAR - BANK RAKYAT"
    "CGC GLENMARIE":           "SA7",    # LRT3 Glenmarie (GTFS "GLENMARIE 2")
}


def build_name_index(stops):
    """GTFS name (full + base before ' - ') -> stop_id."""
    idx = {}
    for sid, info in stops.items():
        nm = info["name"].upper()
        idx.setdefault(nm, sid)
        base = nm.split(" - ")[0].strip()
        idx.setdefault(base, sid)
    return idx


def map_station(label, name_idx, all_names):
    """'KJ10: KLCC' -> stop_id, via override / exact name / fuzzy."""
    name = label.split(":", 1)[1].strip().upper() if ":" in label else label.upper()
    if name in NAME_OVERRIDES:
        return NAME_OVERRIDES[name]
    if name in name_idx:
        return name_idx[name]
    hit = process.extractOne(name, all_names, scorer=fuzz.token_sort_ratio)
    if hit and hit[1] >= 90:
        return name_idx[hit[0]]
    return None


def main():
    print("[1/4] Loading O-D parquet...")
    df = pd.read_parquet(PARQUET)
    df = df[(df["origin"] != "A0: All Stations") & (df["destination"] != "A0: All Stations")]
    # Aggregate total trips per O-D pair over the whole period (abs value is
    # irrelevant — only relative busyness matters after normalisation).
    od = df.groupby(["origin", "destination"], as_index=False)["ridership"].sum()
    print(f"      {len(od):,} distinct O-D pairs over {df['date'].min().date()}..{df['date'].max().date()}")

    print("[2/4] Building station graph + name mapping...")
    stops, route_stop_seq, _, edge_minutes = rr._load_gtfs()
    G = rr._build_graph(stops, route_stop_seq, None, None, edge_minutes)
    name_idx = build_name_index(stops)
    all_names = list(name_idx.keys())

    labels = pd.concat([od["origin"], od["destination"]]).unique()
    label2sid = {}
    unmapped = []
    for lb in labels:
        sid = map_station(lb, name_idx, all_names)
        if sid:
            label2sid[lb] = sid
        else:
            unmapped.append(lb)
    print(f"      mapped {len(label2sid)}/{len(labels)} stations; unmapped: {unmapped}")

    print("[3/4] Assigning trips to path segments...")
    seg_load = {}
    paths = 0
    no_path = 0
    for _, row in od.iterrows():
        o = label2sid.get(row["origin"])
        d = label2sid.get(row["destination"])
        if not o or not d or o == d or o not in G or d not in G:
            continue
        try:
            path = nx.shortest_path(G, o, d, weight="weight")
        except nx.NetworkXNoPath:
            no_path += 1
            continue
        paths += 1
        trips = int(row["ridership"])
        for u, v in zip(path, path[1:]):
            if G[u][v].get("route_id") == "INTERCHANGE":
                continue  # walking transfer, not a train leg
            key = "|".join(sorted([u, v]))
            seg_load[key] = seg_load.get(key, 0) + trips
    print(f"      assigned {paths:,} pairs ({no_path} had no path); {len(seg_load)} segments loaded")

    print("[4/4] Normalising + writing...")
    mx = max(seg_load.values()) if seg_load else 1
    out = {k: round(v / mx, 4) for k, v in seg_load.items()}
    out["_meta"] = {
        "source": "ridership_od_rapidrail_daily",
        "date_range": [str(df["date"].min().date()), str(df["date"].max().date())],
        "max_segment_trips": int(mx),
        "segments": len(seg_load),
        "note": "Historical daily-aggregate ridership; no time-of-day. Ratio 0..1 of busiest leg.",
    }
    OUT.write_text(json.dumps(out, indent=1))
    print(f"      wrote {OUT} ({len(seg_load)} segments)")
    # quick peek at busiest legs
    busiest = sorted(seg_load.items(), key=lambda x: -x[1])[:5]
    for k, v in busiest:
        a, b = k.split("|")
        print(f"      busiest: {stops[a]['name']} <-> {stops[b]['name']}  ({v:,} trips)")


if __name__ == "__main__":
    main()
