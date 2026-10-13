"""
What would the intent gate have changed?

The gate asks one language-model question per scraped post that raised an
alert: is this reporting a live service problem, or is it commentary that
merely sounds like one? Turning it on changes how much evidence a confirmation
needs, so the decision should be made against real data rather than against
the three examples that motivated it.

This script replays the posts actually logged in disruption_logs through the
gate and reports:

  * how many alerts it would clear, and the exact text of each
  * how many it would KEEP that look like commentary — the misses
  * which confirmed stations would drop below CONFIRM_WEIGHT as a result

It writes nothing. Every verdict is printed so the gate can be judged on its
reasoning, not just its hit rate: a gate that clears the right number of posts
for the wrong reasons is not safe to turn on.

Cost note — one model call per alert row. The gate is NOT required to be
enabled for this script to run; it calls is_live_report directly.

    cd D:/FYP
    python scripts/replay_intent_gate.py --cases          # no database needed
    python scripts/replay_intent_gate.py --limit 200
    python scripts/replay_intent_gate.py --limit 50 --provider groq
"""
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv                       # noqa: E402
load_dotenv(ROOT / "backend" / ".env")

import time                                          # noqa: E402

import agents.intent_gate as gate                    # noqa: E402
import api.dashboard as dash                         # noqa: E402

WINDOW_MINUTES = 30      # same corroboration window the live board uses


# ── fixed cases: what the gate is SUPPOSED to do ─────────────────────────────
# Usable without Supabase (--cases), which matters because the replay above
# needs the database and the gate needs judging either way. The "reject" set is
# taken from posts actually found in the log audit; the "keep" set is what a
# real commuter report looks like, in the three registers the feed receives:
# English, Malay, and mixed.
#
# A gate that rejects everything would score 100% on the reject set, so both
# halves are always reported together. The keep set is the one that matters:
# every miss there is a real disruption the board would confirm late or never.

CASES_REJECT = [
    "lrt kj rosak sebab loke letak jawatan ke",
    "i pejuang lrt kelana jaya line 😂",
    "Dikecam MRT interchange cancelled, LRT3 delayed, contractor kecil angry",
    "LRT3 trains are unreliable, do not gamble lives",
    "kenapa lrt kita tak macam singapore mrt, memalukan betul",
    "i want to go to mid valley",
    "how much is the fare from kl sentral to klcc on the lrt",
    "jakarta mrt is so much cleaner than ours",
    "throwback to when the kelana jaya line first opened in 1998",
    "rapidkl should extend the ampang line operating hours",
    "berita: lrt3 dijangka siap pada 2027, kata menteri",
    "my train was broken down yesterday, worst commute of my life",
]

CASES_KEEP = [
    "stuck at masjid jamek for 30 minutes, no train coming",
    "LRT rosak kat kampung baru, semua terkandas kat platform",
    "kelana jaya line down now, everyone offloaded at pasar seni",
    "tren KJ tergendala, ramai tunggu kat platform sekarang",
    "ampang line so packed right now, cannot even board three trains",
    "power trip kat lrt ampang, lampu semua mati dalam tren",
    "monorail stopped between hang tuah and imbi, nobody said anything",
    "MRT kajang line delayed, signalling fault announced at tun razak exchange",
    "bas gantian disediakan dari taman bahagia ke kelana jaya",
    "doors wont close at dang wangi, train held for 10 mins already",
]


def run_cases(delay: float) -> None:
    """Score the gate on the fixed cases. No database needed."""
    print("FIXED CASES — reject commentary, keep real reports")
    print(f"provider order: {gate.GATE_PROVIDER} first · {delay}s between calls")
    print()

    results = {"reject": [], "keep": []}
    total = len(CASES_REJECT) + len(CASES_KEEP)
    done = 0
    for want, texts in (("reject", CASES_REJECT), ("keep", CASES_KEEP)):
        for t in texts:
            v = gate.is_live_report(t)
            results[want].append((t, v))
            done += 1
            print(f"\r  {done}/{total} checked", end="", flush=True)
            if delay and done < total:
                time.sleep(delay)
    print("\r" + " " * 40 + "\r", end="")

    def report(want, label, correct_when_live):
        rows = results[want]
        checked = [(t, v) for t, v in rows if v["checked_by"] is not None]
        if not checked:
            print(f"{label}: no verdict for any case — provider unavailable.")
            return None
        right = [(t, v) for t, v in checked if v["live"] is correct_when_live]
        wrong = [(t, v) for t, v in checked if v["live"] is not correct_when_live]
        print(f"{label}  {len(right)}/{len(checked)} correct"
              + (f"  ({len(rows) - len(checked)} unchecked)"
                 if len(checked) != len(rows) else ""))
        for t, v in wrong:
            print(f"    MISS [{v['why']}] {t[:80]}")
        print()
        return len(right), len(checked)

    kept = report("keep", "REAL REPORTS KEPT    ", True)
    rej = report("reject", "COMMENTARY REJECTED  ", False)

    if kept and rej:
        print("Read the KEEP misses first. A rejected real report is a")
        print("disruption the board confirms late or never, which is the error")
        print("this system exists to avoid. A kept joke only costs 0.4 weight.")
        if kept[0] < kept[1]:
            print("There is at least one. Do NOT enable the gate until the")
            print("prompt no longer makes that mistake.")
        elif rej[0] == rej[1]:
            print("Both sets are clean on these cases. That justifies enabling")
            print("it behind INTENT_GATE=1 and watching the gated count, not")
            print("treating the filter as proven on live traffic.")


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
        print("SUPABASE_URL / key not set in backend/.env — nothing to replay.")
        return []
    sb = create_client(url, key)
    res = (sb.table("disruption_logs")
             .select("text,created_at,source,disruption_alert,method")
             .order("created_at", desc=True).limit(limit).execute())
    return res.data or []


def station_weights(rows: list[dict]) -> dict[str, float]:
    """Peak corroboration weight each station reaches in any 30-minute window.

    Approximates what the live board computes: group alert rows by station,
    slide a window over them, and sum the source weight of each DISTINCT text
    inside it. Reported per station so the gate's effect on confirmations can
    be read directly, not inferred from the number of posts it removed.
    """
    per_station: dict[str, list] = defaultdict(list)
    for r in rows:
        ts = parse_ts(r.get("created_at", ""))
        if not ts:
            continue
        for name, _ids in dash._detect_stations(r.get("text", "")):
            per_station[name].append((ts, norm(r.get("text", "")),
                                      r.get("source") or "x_live"))

    peaks: dict[str, float] = {}
    span = timedelta(minutes=WINDOW_MINUTES)
    for name, items in per_station.items():
        items.sort()
        best = 0.0
        for i, (start, _t, _s) in enumerate(items):
            window = {}
            for ts, text, src in items[i:]:
                if ts - start > span:
                    break
                # keep the highest-weighted source for a repeated text, which
                # is what _signal_weight does
                if text not in window or \
                        dash._source_weight(src) > dash._source_weight(window[text]):
                    window[text] = src
            best = max(best, dash._signal_weight(window))
        peaks[name] = best
    return peaks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200,
                    help="how many recent rows to read (default 200)")
    ap.add_argument("--delay", type=float, default=4.0,
                    help="seconds between model calls. Measured, not guessed: "
                         "1.5s exhausted the Gemini free-tier per-minute quota "
                         "after 16 calls and the rest of the run reported "
                         "nothing. 4.0 completed cleanly (default 4.0)")
    ap.add_argument("--provider", choices=["gemini", "groq"],
                    help="which provider to try first")
    ap.add_argument("--cases", action="store_true",
                    help="score the fixed cases instead of the log (no DB)")
    args = ap.parse_args()

    if args.provider:
        gate.GATE_PROVIDER = args.provider

    if args.cases:
        return run_cases(args.delay)

    try:
        rows = fetch(args.limit)
    except Exception as e:
        print(f"could not read disruption_logs: {type(e).__name__}: {str(e)[:100]}")
        return
    if not rows:
        return

    alerts = [r for r in rows if r.get("disruption_alert") and r.get("text")]
    print(f"{len(rows)} rows read · {len(alerts)} raised an alert")
    if not alerts:
        return

    # Official announcements are never gated, so they are not replayed either.
    gated_rows = [r for r in alerts if (r.get("source") or "") != "x_official"]
    skipped = len(alerts) - len(gated_rows)
    print(f"{len(gated_rows)} to replay ({skipped} official, never gated)")
    print(f"provider order: {gate.GATE_PROVIDER} first · "
          f"{args.delay}s between calls")
    print()

    cleared, kept, unchecked = [], [], []
    for i, r in enumerate(gated_rows, 1):
        v = gate.is_live_report(r["text"])
        if v["checked_by"] is None:
            unchecked.append(r)
        elif v["live"]:
            kept.append((r, v))
        else:
            cleared.append((r, v))
        print(f"\r  {i}/{len(gated_rows)} replayed", end="", flush=True)
        if args.delay and i < len(gated_rows):
            time.sleep(args.delay)
    print("\r" + " " * 40 + "\r", end="")

    checked = len(cleared) + len(kept)
    if not checked:
        print("No verdict was obtained for any post — the providers are")
        print("unavailable or out of quota. Nothing can be concluded from this")
        print("run; it is not evidence that the gate changes nothing.")
        return
    if unchecked:
        print(f"NOTE: {len(unchecked)} of {len(gated_rows)} posts got no verdict "
              f"(fail-open). They are excluded from the rates below rather than")
        print("      counted as 'kept', which would flatter the gate.")
        print()

    print(f"VERDICTS  ({checked} posts checked)")
    print(f"  alert kept     {len(kept):>4}   ({len(kept)/checked:.0%})")
    print(f"  alert cleared  {len(cleared):>4}   ({len(cleared)/checked:.0%})")
    print()

    if cleared:
        print("CLEARED — these would stop contributing corroboration weight")
        for r, v in cleared[:25]:
            print(f"  [{v['why']}] {norm(r['text'])[:90]}")
        if len(cleared) > 25:
            print(f"  ... and {len(cleared) - 25} more")
        print()
        print("  Read every line. If any of these is a genuine commuter report,")
        print("  the gate is too aggressive and must not be enabled — a cleared")
        print("  real report is a disruption the board confirms later or never.")
        print()

    print("KEPT — a sample, to check the gate is not simply passing everything")
    for r, v in kept[:10]:
        print(f"  [{v['why']}] {norm(r['text'])[:90]}")
    print()

    # ── effect on confirmations ─────────────────────────────────────────────
    cleared_texts = {norm(r["text"]) for r, _v in cleared}
    before = station_weights(alerts)
    after = station_weights([r for r in alerts
                             if norm(r.get("text", "")) not in cleared_texts])

    changed = [(n, before[n], after.get(n, 0.0)) for n in before
               if abs(before[n] - after.get(n, 0.0)) > 1e-9]
    print("EFFECT ON CONFIRMATIONS "
          f"(peak weight in any {WINDOW_MINUTES}-minute window, "
          f"threshold {dash.CONFIRM_WEIGHT})")
    if not changed:
        print("  No station's peak corroboration changes. Either the cleared")
        print("  posts named no station, or they were never part of a peak —")
        print("  so the gate removes noise from the feed without affecting any")
        print("  confirmation in this sample.")
    else:
        print(f"  {'station':<20}{'before':<9}{'after':<9}outcome")
        for name, b, a in sorted(changed, key=lambda x: -(x[1] - x[2])):
            was = b >= dash.CONFIRM_WEIGHT
            now = a >= dash.CONFIRM_WEIGHT
            outcome = ("no longer confirms" if was and not now
                       else "still confirms" if now
                       else "was never confirmed")
            print(f"  {name:<20}{b:<9.1f}{a:<9.1f}{outcome}")
        lost = sum(1 for _n, b, a in changed
                   if b >= dash.CONFIRM_WEIGHT > a)
        print()
        print(f"  {lost} confirmation(s) would no longer happen.")
        print("  That is the number to justify: each one is either a false")
        print("  confirmation the gate correctly prevented, or a real")
        print("  disruption it would have hidden. The text above says which.")


if __name__ == "__main__":
    main()
