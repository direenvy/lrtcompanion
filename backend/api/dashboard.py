import csv
import re
import time
from pathlib import Path

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter
from db.supabase_client import _get_client

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

_GTFS_STOPS = (Path(__file__).resolve().parent.parent.parent
               / "data" / "raw" / "gtfs" / "stops.txt")

# Map a GTFS stop_id prefix → line_id used by LINE_META. Keeps line attribution
# faithful to what a station physically serves, so a bare "Masjid Jamek down"
# lights up every line whose platform sits at that station (KJ + AG + PH) and
# leaves untouched lines alone.
_PREFIX_TO_LINE: list[tuple[str, str]] = [
    ("KJ", "KJ"), ("AG", "AG"), ("SP", "PH"), ("PY", "PYL"),
    ("KG", "KGL"), ("MR", "MR"), ("SA", "SA"), ("BRT", "BRT"),
    ("BR", "BRT"),           # BRT stop ids also appear as BR-prefixed
]


def _lines_for_stop(stop_id: str) -> str | None:
    for pref, line_id in _PREFIX_TO_LINE:
        if stop_id.startswith(pref):
            return line_id
    return None


def _lines_for_station_stops(stop_ids: list[str]) -> set[str]:
    return {ln for sid in stop_ids if (ln := _lines_for_stop(sid))}

# Station names that are also everyday Malay/English words — bare mentions
# would misattribute ordinary sentences ("hari merdeka" is a holiday, not an
# incident). They are matched CONDITIONALLY: only when a disruption keyword
# appears in the same text (see _DISRUPTION_CONTEXT below). Keeps the
# false-positive guard while unblocking genuine reports for these 9 stations.
_COMMON_WORD_STATIONS = {"damai", "cahaya", "cempaka", "kerjaya", "wawasan",
                         "subang", "universiti", "merdeka", "surian"}

# Real short station names (< 4 chars) that must be allowed to match. The bare
# len(name) >= 4 rule was blocking every one of these — for now just UPM, but
# any future short GTFS name (e.g. an LRT extension) is added here.
_SHORT_STATION_ALLOW = {"upm"}

# Disruption-context guard for common-word stations: only treat "merdeka" /
# "cahaya" / etc. as a real station report when a disruption verb is nearby.
_DISRUPTION_CONTEXT = re.compile(
    r"\b(?:down|broke(?:n)?|breakdown|breaking|stuck|delay(?:s|ed|ing)?|"
    r"halt(?:ed|ing)?|stopped?|stopping|not\s+moving|not\s+working|"
    r"closed?|jam(?:med)?|disrupt(?:ed|ion|s|ing)?|"
    r"rosak|terhenti|tak\s+jalan|tersekat|tak\s+bergerak|masalah)\b",
    re.IGNORECASE,
)


def _station_name_variants(raw: str):
    """Lower-cased name variants for matching. Sponsored names
    ('KAMPUNG BARU - CBP COOPBANK PERTAMA') also yield the base name
    commuters actually use ('kampung baru')."""
    name = raw.strip().lower()
    yield name
    if " - " in name:
        base = name.split(" - ")[0].strip()
        if len(base) >= 4:
            yield base


def _load_station_lines() -> list[tuple[str, str]]:
    """(station_name_lower, line_id) for stations unique to one line,
    longest name first so 'ampang park' wins over 'ampang'."""
    names: dict[str, set] = {}
    try:
        with _GTFS_STOPS.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                rid = "KGL" if row["route_id"] == "MRT" else row["route_id"]
                for variant in _station_name_variants(row["stop_name"]):
                    names.setdefault(variant, set()).add(rid)
    except Exception:
        return []
    # Ambiguous names (interchanges serving several lines) are kept with
    # line_id None: matching one BLOCKS attribution, so "ampang park" (KJ+PYL)
    # never falls through to the shorter "ampang" (AG) station inside it.
    entries = [(n, next(iter(r)) if len(r) == 1 else None)
               for n, r in names.items()
               if n not in _COMMON_WORD_STATIONS
               and (len(n) >= 4 or n in _SHORT_STATION_ALLOW)]
    return sorted(entries, key=lambda x: len(x[0]), reverse=True)


_STATION_LINES = _load_station_lines()


def _load_station_stops() -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Regular station names (always match), conditional common-word names
    (match only in a disruption context), and name -> [stop_ids] across all
    lines sharing that name — interchanges map to every platform's stop_id.
    Commuter nicknames from _STATION_ALIASES (TRX/TTDI/BST/KLSENTRAL/...) are
    seeded as extra entries so a report using an alias detects like the full
    name, mirroring what the routing side already knows."""
    ids: dict[str, list[str]] = {}
    try:
        with _GTFS_STOPS.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                for variant in _station_name_variants(row["stop_name"]):
                    ids.setdefault(variant, []).append(row["stop_id"])
    except Exception:
        return [], [], {}

    regular = [n for n in ids
               if n not in _COMMON_WORD_STATIONS
               and (len(n) >= 4 or n in _SHORT_STATION_ALLOW)]
    conditional = [n for n in ids if n in _COMMON_WORD_STATIONS]

    # Seed commuter nicknames (from rerouting_agent._STATION_ALIASES) so a
    # bare "TRX broke down" lights up the board the same as the full name.
    # Import lazily to avoid a circular import at module load.
    try:
        from agents.rerouting_agent import _STATION_ALIASES  # type: ignore
        for alias, target in _STATION_ALIASES.items():
            alias_lower = alias.lower()
            if alias_lower in ids:
                continue                                # already a real name
            target_lower = target.lower()
            candidates = [target_lower]
            if " - " in target_lower:
                candidates.append(target_lower.split(" - ")[0].strip())
            for cand in candidates:
                if cand in ids:
                    ids[alias_lower] = list(ids[cand])
                    # A nickname is always safe (unambiguous initialism), so it
                    # goes in the regular list even if its target is a
                    # common-word station like UNIVERSITI.
                    regular.append(alias_lower)
                    break
    except Exception:
        pass

    regular.sort(key=len, reverse=True)
    conditional.sort(key=len, reverse=True)
    return regular, conditional, ids


_STATION_NAMES, _CONDITIONAL_STATION_NAMES, _STATION_STOP_IDS = _load_station_stops()

# One anonymous report must not reroute every user (griefing vector), and a
# passively-scraped tweet is far weaker evidence than a deliberate in-app or
# voice report from an actual user of this system. Corroboration is therefore
# SOURCE-WEIGHTED: distinct signals accumulate weight, and a line/station is
# only CONFIRMED disrupted once total weight reaches CONFIRM_WEIGHT.
#   - in-app / voice report  → 1.0  (2 reports confirm — deliberate, high-trust)
#   - external tweet (x_live) → 0.4  (~5 distinct tweets confirm — low-trust,
#                                      could be politics, news, or opinion)
# This kills the single-political-tweet false alarm (0.4 < 2.0) while keeping
# the in-app/demo path responsive and preserving anti-griefing (needs 2 people).
CONFIRM_WEIGHT   = 2.0
EXTERNAL_WEIGHT  = 0.4
INTERNAL_SOURCES = {"user", "voice"}        # deliberate in-app/voice reports → 1.0
OFFICIAL_SOURCES = {"x_official"}           # official Rapid KL announcement → authoritative


def _source_weight(src: str) -> float:
    """Trust weight per source (the corroboration hierarchy):
      official Rapid KL announcement → confirms alone (>= CONFIRM_WEIGHT)
      deliberate in-app / voice report → 1.0 (two confirm)
      anonymous scraped tweet → 0.4 (several needed; could be noise/opinion)."""
    if src in OFFICIAL_SOURCES:
        return CONFIRM_WEIGHT
    if src in INTERNAL_SOURCES:
        return 1.0
    return EXTERNAL_WEIGHT


def _signal_weight(text_to_source: dict[str, str]) -> float:
    """Total corroboration weight from distinct normalised texts (spam already
    deduped by the dict key), each weighted by its most trusted source."""
    return sum(_source_weight(src) for src in text_to_source.values())


def _derive_station_disruptions(all_alerts: list[dict],
                                cutoff_30m: str) -> tuple[list[dict], list[dict]]:
    """Split stations named in red-window alerts into corroborated
    (auto-avoid) and advisory (uncorroborated). Corroboration is
    source-weighted (see CONFIRM_WEIGHT above): distinct texts spammed twice
    count once, and an in-app report outweighs a scraped tweet."""
    per_station: dict[str, dict] = {}
    for row in all_alerts:
        if row["created_at"] < cutoff_30m:
            continue
        norm_text = " ".join((row.get("text") or "").lower().split())
        src = row.get("source", "user")
        for name, stop_ids in _detect_stations(row.get("text", "")):
            entry = per_station.setdefault(name, {
                "name": name.upper(), "stop_ids": stop_ids,
                "last_alert_at": row["created_at"], "text_src": {}, "sources": set(),
            })
            # keep the most trusted source seen for each distinct text
            prev = entry["text_src"].get(norm_text)
            if prev is None or _source_weight(src) > _source_weight(prev):
                entry["text_src"][norm_text] = src
            entry["sources"].add(src)
            if row["created_at"] > entry["last_alert_at"]:
                entry["last_alert_at"] = row["created_at"]

    disrupted, advisory = [], []
    for entry in per_station.values():
        weight = _signal_weight(entry["text_src"])
        out = {"name": entry["name"], "stop_ids": entry["stop_ids"],
               "last_alert_at": entry["last_alert_at"],
               "report_count": len(entry["text_src"]),
               "corroboration": round(weight, 1),
               "sources": sorted(entry["sources"])}
        if weight >= CONFIRM_WEIGHT:
            disrupted.append(out)
        else:
            advisory.append(out)
    return disrupted, advisory


def _detect_stations(text: str) -> list[tuple[str, list[str]]]:
    """(station_name, stop_ids) for every station explicitly named in the text.
    Longest name first; matched spans are masked so 'ampang' cannot re-match
    inside an already-matched 'ampang park'."""
    lower = text.lower()
    found: list[tuple[str, list[str]]] = []
    for name in _STATION_NAMES:
        # '<station> line' names the LINE, not the station — don't block it
        pattern = r"\b" + re.escape(name) + r"\b(?!\s+line\b)"
        if re.search(pattern, lower):
            found.append((name, _STATION_STOP_IDS[name]))
            lower = re.sub(pattern, " ", lower)
    # Common-word station names (merdeka/subang/…) are matched only when the
    # text itself carries a disruption verb — a bare "hari merdeka" stays
    # ignored, while "merdeka station down" fires.
    if _DISRUPTION_CONTEXT.search(text):
        for name in _CONDITIONAL_STATION_NAMES:
            pattern = r"\b" + re.escape(name) + r"\b(?!\s+line\b)"
            if re.search(pattern, lower):
                found.append((name, _STATION_STOP_IDS[name]))
                lower = re.sub(pattern, " ", lower)
    return found

LINE_META = {
    "KJ":  {"name": "Kelana Jaya",    "color": "#ef4444", "keywords": ["kelana jaya", "kj line", " kj "]},
    "AG":  {"name": "Ampang",         "color": "#f97316", "keywords": ["ampang"]},
    "PH":  {"name": "Sri Petaling",   "color": "#ec4899", "keywords": ["sri petaling"]},
    "KGL": {"name": "MRT Kajang",     "color": "#22c55e", "keywords": ["mrt kajang", "kajang"]},
    "PYL": {"name": "MRT Putrajaya",  "color": "#eab308", "keywords": ["mrt putrajaya", "putrajaya"]},
    "MR":  {"name": "Monorail",       "color": "#84cc16", "keywords": ["monorail", "kl monorail"]},
    "BRT": {"name": "BRT Sunway",     "color": "#10b981", "keywords": ["brt", "sunway"]},
    "SA":  {"name": "LRT Shah Alam",  "color": "#38bdf8", "keywords": ["shah alam", "lrt3", "johan setia"]},
}


# STRONG, unambiguous line identifiers — phrases that can ONLY mean a line,
# never a station. These win before station-name matching so that an explicit
# line mention disambiguates an interchange station shared between lines
# (e.g. "LRT3 ... at Glenmarie" → SA, not KJ, even though "Glenmarie" is a KJ
# station and the LRT3 platform there is named "Glenmarie 2"). Weak place-ish
# keywords ("shah alam", "ampang", "kajang") stay in the fallback below, so a
# destination mention does not override the actual disrupted station.
_STRONG_LINE_KEYWORDS = [
    ("lrt3", "SA"), ("shah alam line", "SA"),
    ("kelana jaya line", "KJ"), ("kj line", "KJ"),
    ("ampang line", "AG"),
    ("sri petaling line", "PH"),
    ("mrt kajang", "KGL"), ("kajang line", "KGL"),
    ("mrt putrajaya", "PYL"), ("putrajaya line", "PYL"),
    ("kl monorail", "MR"), ("monorail line", "MR"),
]


def _detect_line(text: str) -> str | None:
    lower = text.lower()
    # 0. Strong, explicit line names win first (disambiguates interchanges).
    for kw, line_id in _STRONG_LINE_KEYWORDS:
        if kw in lower:
            return line_id
    # 1. Station names (longest first). A None line_id means the station
    #    serves several lines — a bare mention cannot pick one, so stop there.
    for name, line_id in _STATION_LINES:
        if re.search(r"\b" + re.escape(name) + r"\b", lower):
            return line_id
    # 2. Fall back to weak (place-ish) line-name keywords.
    for line_id, meta in LINE_META.items():
        for kw in meta["keywords"]:
            if kw in lower:
                return line_id
    return None


@router.get("/stats")
def get_stats():
    """Aggregate stats + recent rows from all 3 logging tables."""
    sb = _get_client()
    if not sb:
        return {"error": "Supabase not connected"}

    # ── disruption_logs ──────────────────────────────────────────────────────
    total_scans   = sb.table("disruption_logs").select("id", count="exact").execute().count or 0
    total_alerts  = sb.table("disruption_logs").select("id", count="exact").eq("disruption_alert", True).execute().count or 0

    sent_rows     = sb.table("disruption_logs").select("sentiment").execute().data or []
    sentiment_counts = {"negative": 0, "neutral": 0, "positive": 0}
    for r in sent_rows:
        s = r.get("sentiment", "")
        if s in sentiment_counts:
            sentiment_counts[s] += 1

    recent_disruptions = (
        sb.table("disruption_logs")
        .select("id,text,sentiment,issue_type,disruption_alert,created_at,source")
        .order("created_at", desc=True)
        .limit(10)
        .execute()
        .data or []
    )

    # ── chat_logs ────────────────────────────────────────────────────────────
    total_chats = sb.table("chat_logs").select("id", count="exact").execute().count or 0

    recent_chats = (
        sb.table("chat_logs")
        .select("id,question,mode,created_at")
        .order("created_at", desc=True)
        .limit(8)
        .execute()
        .data or []
    )

    # ── feedback_logs ────────────────────────────────────────────────────────
    thumbs_up   = sb.table("feedback_logs").select("id", count="exact").eq("rating", 1).execute().count or 0
    thumbs_down = sb.table("feedback_logs").select("id", count="exact").eq("rating", -1).execute().count or 0

    return {
        "disruptions": {
            "total_scans":       total_scans,
            "total_alerts":      total_alerts,
            "sentiment_counts":  sentiment_counts,
            "recent":            recent_disruptions,
        },
        "chats": {
            "total":   total_chats,
            "recent":  recent_chats,
        },
        "feedback": {
            "thumbs_up":   thumbs_up,
            "thumbs_down": thumbs_down,
        },
    }


@router.get("/line-status")
def get_line_status():
    """
    Per-line disruption status derived from recent disruption_logs.
    Status logic:
      RED   (disrupted)  — alert logged in last 30 min
      AMBER (recovering) — alert logged 30 min – 4 hr ago
      GREEN (normal)     — no recent alerts
    """
    sb = _get_client()

    now = datetime.now(timezone.utc)
    cutoff_4h   = (now - timedelta(hours=4)).isoformat()
    cutoff_30m  = (now - timedelta(minutes=30)).isoformat()

    all_alerts: list[dict] = []
    degraded = False
    # With no network the two attempts plus the retry pause cost ~3 s to reach
    # the same degraded snapshot the breaker already knows is coming.
    from agents.net_guard import is_offline, mark_offline, mark_online
    if sb and is_offline():
        sb, degraded = None, True
    if sb:
        # One-shot retry: a momentary DNS/network blip (e.g. wifi reconnecting)
        # should not blank the board — retry once before degrading. Only if BOTH
        # attempts fail do we serve the honest all-normal snapshot.
        last_err = None
        for attempt in range(2):
            try:
                rows = (
                    sb.table("disruption_logs")
                    .select("id,text,sentiment,issue_type,created_at,source")
                    .eq("disruption_alert", True)
                    .gte("created_at", cutoff_4h)
                    .order("created_at", desc=True)
                    .limit(200)
                    .execute()
                    .data or []
                )
                all_alerts = rows
                last_err = None
                mark_online()
                break
            except Exception as e:
                last_err = e
                if attempt == 0:
                    time.sleep(0.6)   # brief pause, then one retry
        if last_err is not None:
            mark_offline()
            print(f"[LineStatus] Supabase unreachable after retry, serving "
                  f"degraded snapshot: {last_err}")
            degraded = True

    # Annotate each alert with detected line AND detected station.
    # An interchange (e.g. Masjid Jamek serves KJ+AG+PH) has NO single line, so
    # line attribution returns None — yet the station IS detected and routing
    # already avoids it. The feed must therefore surface line-OR-station, or a
    # multi-line interchange disruption stays invisible on the board despite
    # being acted upon when planning a trip.
    for row in all_alerts:
        line = _detect_line(row.get("text", ""))
        stations = _detect_stations(row.get("text", ""))
        row["detected_line"] = line                                   # kept for feed
        row["detected_station"] = stations[0][0].upper() if stations else None
        # Which line(s) does this alert actually implicate?
        #   - explicit line named ("kelana jaya line down")  → just that line
        #   - bare station named ("masjid jamek down")        → every line the
        #     station serves (an interchange breaks all its platforms at once)
        #   - neither                                         → no line
        if line:
            row["implicated_lines"] = {line}
        elif stations:
            row["implicated_lines"] = set()
            for _n, stop_ids in stations:
                row["implicated_lines"] |= _lines_for_station_stops(stop_ids)
        else:
            row["implicated_lines"] = set()

    # Build per-line status with the SAME source-weighted corroboration as
    # stations: a single scraped tweet (weight 0.4) shows as "unconfirmed",
    # never "disrupted"; confirmation needs weight >= 2.0 (2 in-app reports or
    # ~5 distinct tweets). Kills single-political-tweet false alarms.
    lines = {}
    for line_id, meta in LINE_META.items():
        # An alert counts for this line if it either NAMES the line, OR names a
        # station that PHYSICALLY serves the line. So "Masjid Jamek down" lights
        # up KJ + AG + PH (all three platforms are at that station), while a KJ
        # station like "Wangsa Maju down" leaves AG/PH untouched. Faithful to
        # the real network: a broken interchange breaks every line through it.
        line_alerts = [r for r in all_alerts if line_id in r["implicated_lines"]]
        recent_alerts = [r for r in line_alerts if r["created_at"] >= cutoff_30m]
        text_src: dict[str, str] = {}
        for r in recent_alerts:
            nt = " ".join((r.get("text") or "").lower().split())
            src = r.get("source", "user")
            prev = text_src.get(nt)
            if prev is None or _source_weight(src) > _source_weight(prev):
                text_src[nt] = src
        weight = _signal_weight(text_src)

        if weight >= CONFIRM_WEIGHT:
            status = "disrupted"
        elif text_src:
            status = "unconfirmed"
        elif line_alerts:
            status = "recovering"
        else:
            status = "normal"

        last = line_alerts[0] if line_alerts else None
        # Drill-down: which station(s) on THIS line are named in its recent
        # reports. Lets the UI show "Kelana Jaya — issue at Masjid Jamek" when
        # you open the card, instead of just a red line with no location.
        # Populate from the full 4-h window (not the 30-min red window) so the
        # 📍 chip stays present after a line transitions RED→AMBER — otherwise
        # a recovering line loses its cause while still amber on the board.
        affected_stations = sorted({
            r["detected_station"] for r in line_alerts if r.get("detected_station")
        })
        lines[line_id] = {
            "line_id":        line_id,
            "name":           meta["name"],
            "color":          meta["color"],
            "status":         status,
            "alert_count_4h": len(line_alerts),
            "last_alert":     last,
            "affected_stations": affected_stations,   # station drill-down
            # exposed so the UI can show WHY a line is/isn't confirmed
            "corroboration":  round(weight, 1),
            "confirm_weight": CONFIRM_WEIGHT,
        }

    # Recent incident feed — include anything attributable to one or more lines
    # (via explicit line name OR via a station that serves those lines).
    recent_feed = sorted(
        [r for r in all_alerts if r["implicated_lines"] or r["detected_station"]],
        key=lambda r: r["created_at"],
        reverse=True,
    )[:20]

    disrupted_stations, advisory_stations = _derive_station_disruptions(
        all_alerts, cutoff_30m)

    return {
        "lines":       lines,
        "recent_feed": recent_feed,
        "disrupted_stations": disrupted_stations,   # corroborated → auto-avoided
        "advisory_stations":  advisory_stations,    # single report → informational
        "degraded":    degraded,   # True = DB unreachable; statuses are a fallback, not truth
        "generated_at": now.isoformat(),
    }


@router.get("/incidents")
def get_incidents(hours: int = 168, limit: int = 300):
    """
    Full incident history for the "All Incidents" page — a wider window than the
    4-hour line-status feed. Returns every logged disruption alert over the last
    `hours` (default 7 days), annotated with its detected line's name and colour
    and its source, so the page renders without a second round-trip.
    """
    sb = _get_client()
    now = datetime.now(timezone.utc)
    hours = max(1, min(hours, 720))        # clamp 1h .. 30d
    limit = max(1, min(limit, 500))
    cutoff = (now - timedelta(hours=hours)).isoformat()

    rows: list[dict] = []
    degraded = False
    if sb:
        try:
            rows = (
                sb.table("disruption_logs")
                .select("id,text,sentiment,issue_type,created_at,source")
                .eq("disruption_alert", True)
                .gte("created_at", cutoff)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
                .data or []
            )
        except Exception as e:
            print(f"[Incidents] Supabase unreachable, serving degraded snapshot: {e}")
            degraded = True

    incidents = []
    for row in rows:
        line_id = _detect_line(row.get("text", ""))
        meta = LINE_META.get(line_id) if line_id else None
        incidents.append({
            **row,
            "detected_line": line_id,
            "line_name":  meta["name"]  if meta else None,
            "line_color": meta["color"] if meta else None,
        })

    return {
        "incidents":    incidents,
        "count":        len(incidents),
        "window_hours": hours,
        "degraded":     degraded,
        "generated_at": now.isoformat(),
    }
