"""
Create the evidence folder tree for the station 500m walk-safety survey.

STRUCTURE (simple, chosen after paring back an earlier over-engineered version):

    data/raw/station_walk_safety/evidence/
      README_INTERCHANGES.txt          <- one file listing where interchanges live
      KJ Kelana Jaya/
        KJ01 GOMBAK/
          1 street_lights/
          2 people_nearby/
          3 safe_crossing/
          4 bushes_nearby/
          5 fenced/
        KJ13 MASJID JAMEK/             <- interchange: real folder only, no stubs
        ...

RULES
  * 161 unique PHYSICAL stations — each appears once, under its first line in
    LINE_ORDER (so Masjid Jamek lives under KJ, Putra Heights under KJ, etc.).
  * Interchanges are documented in README_INTERCHANGES.txt at the top of the
    tree — no stub folders under the other lines.
  * Multiple exits: NOT modelled here. Rate the station on its worst exit and
    describe the difference in the CSV's `area_context` column.
  * Codes are the official Rapid KL stop_ids (= GTFS stop_ids), zero-padded to
    2 digits so Explorer sorts them correctly (KJ01, KJ02, …, KJ13, …, KJ37).

The script is idempotent — re-run any time to add missing folders. It never
deletes user files or images.

Usage (from D:/FYP):
    python scripts/make_safety_evidence_folders.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from agents.rerouting_agent import _load_gtfs

EVID = ROOT / "data" / "raw" / "station_walk_safety" / "evidence"

LINE_ORDER = ["KJ", "AG", "PH", "KGL", "PYL", "MR", "BRT", "SA"]
LINE_NAME = {
    "KJ": "Kelana Jaya", "AG": "Ampang", "PH": "Sri Petaling",
    "KGL": "MRT Kajang", "PYL": "MRT Putrajaya", "MR": "Monorail",
    "BRT": "BRT Sunway", "SA": "LRT Shah Alam",
}
ATTRIBUTES = ["street_lights", "people_nearby", "safe_crossing",
              "bushes_nearby", "fenced"]


def safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in " -" else "_" for c in name).strip()


def pad_code(stop_id: str) -> str:
    """KJ7 -> KJ07, AG7 -> AG07, KG18A -> KG18A."""
    m = re.fullmatch(r"([A-Z]+)(\d+)([A-Z]?)", stop_id)
    if not m:
        return stop_id
    prefix, num, suffix = m.groups()
    return f"{prefix}{int(num):02d}{suffix}"


def line_prefix(route_seq, ln):
    ids = route_seq.get(ln, [])
    m = re.match(r"([A-Z]+)", ids[0]) if ids else None
    return m.group(1) if m else ln


def main() -> None:
    stops, route_seq, _names, _emin = _load_gtfs()

    def clean(sid):
        return stops[sid]["name"].split(" - ")[0].strip()

    # Owner-line assignment (first line in LINE_ORDER that serves the station).
    owner_line = {}
    owner_sid = {}
    other_lines = {}       # for the interchanges README
    for ln in LINE_ORDER:
        for sid in route_seq.get(ln, []):
            name = clean(sid)
            if not name:
                continue
            if name not in owner_line:
                owner_line[name] = ln
                owner_sid[name] = sid
            else:
                other_lines.setdefault(name, []).append(ln)

    # Build the tree: only real folders (per owner line), attribute subfolders.
    created = 0
    for ln in LINE_ORDER:
        pref = line_prefix(route_seq, ln)
        line_dir = EVID / f"{pref} {LINE_NAME[ln]}"
        ids = sorted(route_seq.get(ln, []),
                     key=lambda s: (re.match(r"[A-Z]+", s).group(0),
                                    int(re.search(r"\d+", s).group(0))))
        for sid in ids:
            name = clean(sid)
            if not name or owner_line[name] != ln:
                continue         # not this line's job (interchange under another line)
            station_dir = line_dir / f"{pad_code(sid)} {safe(name)}"
            for ai, attr in enumerate(ATTRIBUTES, start=1):
                d = station_dir / f"{ai} {attr}"
                if not d.exists():
                    d.mkdir(parents=True, exist_ok=True)
                    (d / ".gitkeep").touch()
                    created += 1

    # README — one file that replaces the 26 empty stub folders.
    interchanges = sorted(
        (name for name in other_lines),
        key=lambda n: (LINE_ORDER.index(owner_line[n]), owner_sid[n])
    )
    lines_out = [
        "INTERCHANGE STATIONS — where each one's REAL evidence folder lives.",
        "Each physical station is surveyed ONCE, under its first line's folder.",
        "This file exists so you don't scroll a line's folder looking for a",
        "station that lives under another line.",
        "",
    ]
    for name in interchanges:
        primary = f"{line_prefix(route_seq, owner_line[name])} {LINE_NAME[owner_line[name]]}"
        code = pad_code(owner_sid[name])
        also = [LINE_NAME[l] for l in other_lines[name]]
        lines_out.append(f"  {name:22} -> {primary} / {code}    (also on: {', '.join(also)})")
    readme = EVID / "README_INTERCHANGES.txt"
    readme.write_text("\n".join(lines_out) + "\n", encoding="utf-8")

    print(f"Stations: {len(owner_line)} | attributes each: {len(ATTRIBUTES)}")
    print(f"Interchanges documented in README: {len(interchanges)}")
    print(f"Folders created this run: {created}")
    print(f"Tree root: {EVID}")


if __name__ == "__main__":
    main()
