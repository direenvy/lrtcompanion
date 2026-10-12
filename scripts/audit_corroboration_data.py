"""
What is actually in the disruption log?

Corroboration defends against a threat model — one person rewording a claim to
reach the confirmation threshold alone. The defences built for it (exact-text
dedup, then near-duplicate merging) were designed from that model, not from
observation. This script asks whether the model matches the data:

  * how many reports are near-duplicates of another report
  * how often several reports for one station arrive in a tight burst
  * how many confirmations rested on only two signals — the thinnest possible
  * which stations confirm most often, and on what evidence

None of this proves intent. A burst of similar reports is exactly what a real
disruption produces. The point is to see whether the shapes the defences assume
exist at all, and at what rate, before building anything further.

    cd D:/FYP
    python scripts/audit_corroboration_data.py
    python scripts/audit_corroboration_data.py --limit 3000
"""
import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv                       # noqa: E402
load_dotenv(ROOT / "backend" / ".env")

from rapidfuzz import fuzz                           # noqa: E402
import api.dashboard as dash                         # noqa: E402

BURST_SECONDS = 120


def norm(t: str) -> str:
    return " ".join((t or "").lower().split())


def parse_ts(s: str):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except Exception:
        return None


def fetch(limit: int) -> list[dict]:
    from supabase import create_client
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY", "")
    if not (url and key):
        print("SUPABASE_URL / key not set in backend/.env — nothing to audit.")
        return []
    sb = create_client(url, key)
    res = (sb.table("disruption_logs")
             .select("text,created_at,source,disruption_alert,issue_type,sentiment,method")
             .order("created_at", desc=True).limit(limit).execute())
    return res.data or []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000)
    args = ap.parse_args()

    try:
        rows = fetch(args.limit)
    except Exception as e:
        print(f"could not read disruption_logs: {type(e).__name__}: {str(e)[:100]}")
        return
    if not rows:
        return

    alerts = [r for r in rows if r.get("disruption_alert")]
    print(f"{len(rows)} reports read · {len(alerts)} raised an alert "
          f"({len(alerts)/len(rows):.0%})")
    print("sources: " + ", ".join(f"{k} {v}" for k, v in
                                  Counter(r.get("source") or "?" for r in rows).most_common()))
    print("deciding model: " + ", ".join(f"{k} {v}" for k, v in
                                         Counter(r.get("method") or "(not recorded)"
                                                 for r in rows).most_common()))
    print()

    # ── 1. near-duplicates ──────────────────────────────────────────────────
    texts = [norm(r.get("text", "")) for r in alerts if r.get("text")]
    exact = len(texts) - len(set(texts))
    near = 0
    seen: list[str] = []
    for t in texts:
        if any(fuzz.token_set_ratio(t, s) >= dash.DEDUP_SIMILARITY for s in seen):
            near += 1
        else:
            seen.append(t)
    print("NEAR-DUPLICATES")
    print(f"  exact repeats                     {exact}")
    print(f"  merged at threshold {dash.DEDUP_SIMILARITY:<3}           {near}"
          f"   ({near/len(texts):.0%} of alert reports)")
    print(f"  distinct signals after merging    {len(seen)} of {len(texts)}")
    if near == 0:
        print("  -> no near-duplicates in this data. The merge rule is defending")
        print("     against something that has not happened yet, which is fine as")
        print("     prevention but is not evidence of a problem.")
    print()

    # ── 2. bursts per station ───────────────────────────────────────────────
    per_station: dict[str, list] = defaultdict(list)
    for r in alerts:
        ts = parse_ts(r.get("created_at", ""))
        if not ts:
            continue
        for name, _ids in dash._detect_stations(r.get("text", "")):
            per_station[name].append((ts, norm(r.get("text", "")), r.get("source")))

    bursts = []
    for name, items in per_station.items():
        items.sort()
        for i in range(len(items) - 1):
            gap = (items[i + 1][0] - items[i][0]).total_seconds()
            if 0 <= gap <= BURST_SECONDS:
                bursts.append((name, gap, items[i][1][:40], items[i + 1][1][:40]))

    print(f"BURSTS  (two reports for one station within {BURST_SECONDS}s)")
    print(f"  pairs found                       {len(bursts)}")
    for name, gap, a, b in bursts[:6]:
        print(f"    {name:<18} {gap:>5.0f}s  {a!r} / {b!r}")
    if not bursts:
        print("  -> none. Timing-based defences would currently fire on nothing.")
    else:
        print("  NOTE: a real disruption produces exactly this shape. Tight timing")
        print("  is not evidence of gaming on its own.")
    print()

    # ── 3. how thin are confirmations? ──────────────────────────────────────
    print("STATIONS NAMED IN ALERT REPORTS")
    counts = Counter(name for name, items in per_station.items() for _ in items)
    distinct = {name: len({t for _ts, t, _s in items}) for name, items in per_station.items()}
    print(f"  {'station':<20}{'reports':<9}{'distinct texts':<16}sources")
    for name, n in counts.most_common(10):
        srcs = Counter(s for _ts, _t, s in per_station[name])
        print(f"  {name:<20}{n:<9}{distinct[name]:<16}"
              + ", ".join(f"{k}×{v}" for k, v in srcs.most_common()))
    print()

    thin = [n for n, d in distinct.items() if d == 2]
    print(f"  stations whose evidence is exactly two distinct texts: {len(thin)}")
    if thin:
        print(f"    {', '.join(sorted(thin)[:8])}")
        print("    These are the confirmations a single rewording attack would")
        print("    produce — and also what two genuine witnesses produce. The log")
        print("    cannot tell them apart without an identifier.")


if __name__ == "__main__":
    main()
