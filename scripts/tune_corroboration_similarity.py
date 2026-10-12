"""
Choose the corroboration deduplication threshold from real data.

Corroboration used to deduplicate reports by exact text, so rewording the same
claim produced a second signal and a second helping of weight — one person
reaching CONFIRM_WEIGHT alone. Similarity matching closes most of that, but the
threshold matters in both directions:

  too LOW   two genuine witnesses describing the same event get merged, and a
            real disruption takes longer to confirm
  too HIGH  rewording still works, and the gap stays open

This script replays the reports actually logged in disruption_logs at a range
of thresholds and reports what each would have changed. It also runs a fixed
set of known pairs — rewordings that SHOULD merge, distinct reports that should
NOT — so a threshold can be judged against intent as well as against volume.

    cd D:/FYP
    python scripts/tune_corroboration_similarity.py
    python scripts/tune_corroboration_similarity.py --limit 2000
"""
import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv                       # noqa: E402
load_dotenv(ROOT / "backend" / ".env")

from rapidfuzz import fuzz                           # noqa: E402

THRESHOLDS = [70, 75, 80, 82, 85, 88, 90, 95, 100]


# ── intent cases: what the threshold is SUPPOSED to do ───────────────────────
# "merge" = one person's two phrasings. "separate" = two real witnesses, or two
# genuinely different events at the same station.

SHOULD_MERGE = [
    ("Train broke down at Masjid Jamek, everyone is stuck on the platform",
     "Masjid Jamek LRT breakdown, service completely stopped"),
    ("stuck at KLCC for 30 minutes, no announcement",
     "no announcement, been stuck at KLCC 30 minutes"),
    ("LRT rosak kat Masjid Jamek, semua terkandas",
     "Masjid Jamek LRT rosak, orang ramai terkandas"),
    ("kelana jaya line down at pasar seni",
     "pasar seni kelana jaya line is down"),
    ("Train stopped at Ampang Park, everyone waiting",
     "everyone waiting, train stopped at Ampang Park"),
]

SHOULD_SEPARATE = [
    # same station, genuinely different observations
    ("Train broke down at Masjid Jamek, everyone is stuck on the platform",
     "Masjid Jamek escalator not working again, had to take the stairs"),
    ("stuck at KLCC for 30 minutes, no announcement",
     "KLCC platform is dangerously overcrowded this evening"),
    # NOTE: a same-complaint-different-station pair is deliberately NOT tested.
    # Deduplication runs per station, so two reports about different stations
    # are never compared and their similarity is irrelevant. Including such a
    # case made the threshold look unachievable when nothing was wrong.
    # a report and a reply about it
    ("LRT rosak kat Masjid Jamek",
     "Thanks for the update, taking the bus instead"),
]


def norm(t: str) -> str:
    return " ".join((t or "").lower().split())


def groups_at(texts: list[str], threshold: int) -> int:
    """How many distinct signals these texts collapse to at this threshold."""
    keys: list[str] = []
    for t in texts:
        for k in keys:
            if fuzz.token_set_ratio(t, k) >= threshold:
                break
        else:
            keys.append(t)
    return len(keys)


def intent_scores(threshold: int) -> tuple[int, int]:
    merged = sum(1 for a, b in SHOULD_MERGE
                 if fuzz.token_set_ratio(norm(a), norm(b)) >= threshold)
    kept = sum(1 for a, b in SHOULD_SEPARATE
               if fuzz.token_set_ratio(norm(a), norm(b)) < threshold)
    return merged, kept


def fetch_rows(limit: int) -> list[dict]:
    try:
        from supabase import create_client
    except ImportError:
        print("supabase package not installed — intent cases only.")
        return []
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY", "")
    if not (url and key):
        print("SUPABASE_URL / key not set — intent cases only.")
        return []
    try:
        sb = create_client(url, key)
        res = (sb.table("disruption_logs")
                 .select("text,created_at,source,disruption_alert")
                 .order("created_at", desc=True).limit(limit).execute())
        return res.data or []
    except Exception as e:
        print(f"could not read disruption_logs ({type(e).__name__}: "
              f"{str(e)[:80]}) — intent cases only.")
        return []


# A real pair from the log audit: one official announcement posted in Malay and
# English, one second apart. It shares almost no tokens, so the lexical rule
# counts it twice — the clearest case for a semantic layer.
BILINGUAL = ("kelewatan tren: laluan kelana jaya untuk ke putra heights",
             "train delay: kelana jaya line please be informed towards putra heights")


def run_semantic():
    """Score every intent pair by embedding cosine and suggest a threshold."""
    sys.path.insert(0, str(ROOT / "backend"))
    from agents.rag_agent import _cosine, EMBED_MODEL
    import google.generativeai as genai
    import os as _os
    genai.configure(api_key=_os.getenv("GEMINI_API_KEY"))

    cache: dict = {}

    def emb(t: str):
        if t not in cache:
            r = genai.embed_content(model=EMBED_MODEL, content=t,
                                    task_type="semantic_similarity",
                                    request_options={"timeout": 20})
            cache[t] = r["embedding"]
        return cache[t]

    def score(a, b):
        return _cosine(emb(norm(a)), emb(norm(b)))

    print("SEMANTIC — embedding cosine for each pair")
    print(f"{'want':<10}{'cos':<9}pair")
    print("-" * 86)
    merge_scores, sep_scores = [], []
    for a, b in SHOULD_MERGE + [BILINGUAL]:
        c = score(a, b)
        merge_scores.append(c)
        print(f"{'merge':<10}{c:<9.3f}{a[:60]}")
    for a, b in SHOULD_SEPARATE:
        c = score(a, b)
        sep_scores.append(c)
        print(f"{'separate':<10}{c:<9.3f}{a[:60]}")

    lo_merge, hi_sep = min(merge_scores), max(sep_scores)
    print()
    print(f"lowest should-merge   {lo_merge:.3f}")
    print(f"highest should-separate {hi_sep:.3f}")
    if lo_merge > hi_sep:
        suggested = round((lo_merge + hi_sep) / 2, 2)
        print(f"-> the two groups separate cleanly. Any threshold between them works;")
        print(f"   the midpoint is {suggested}. Prefer nearer the upper end: merging")
        print(f"   too eagerly costs real corroboration, which is the worse error.")
    else:
        print("-> the groups OVERLAP. No cosine threshold separates them either, so")
        print("   embeddings do not close this gap any more than tokens did. Say so")
        print("   rather than picking a number that looks decisive.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000,
                    help="how many recent rows to replay (default 1000)")
    # Lexical matching cannot see across languages or through a full rewrite.
    # This mode scores the same pairs by embedding cosine instead, including a
    # bilingual pair taken from the real log, so the semantic threshold is
    # chosen against the case that motivated it.
    ap.add_argument("--semantic", action="store_true",
                    help="score pairs by embedding cosine instead of tokens")
    args = ap.parse_args()

    if args.semantic:
        return run_semantic()

    print("INTENT — does the threshold do what it is meant to?")
    print(f"{'thresh':<9}{'rewordings merged':<22}{'distinct kept apart':<22}note")
    print("-" * 78)
    best = []
    for t in THRESHOLDS:
        m, k = intent_scores(t)
        perfect = (m == len(SHOULD_MERGE) and k == len(SHOULD_SEPARATE))
        if perfect:
            best.append(t)
        print(f"{t:<9}{f'{m}/{len(SHOULD_MERGE)}':<22}"
              f"{f'{k}/{len(SHOULD_SEPARATE)}':<22}"
              f"{'both correct' if perfect else ''}")
    print()
    if best:
        print(f"Thresholds satisfying every intent case: {best}")
        print(f"Prefer the HIGHEST of those ({max(best)}) — a higher cut-off merges")
        print("less, so it is the more conservative choice when real reports vary")
        print("more than this handful of examples.")
    else:
        print("No threshold satisfies every intent case. Look at which cases fail:")
        print("if rewordings are not merging, the pairs may be more different than")
        print("real ones; if distinct reports merge, token_set_ratio may be too")
        print("forgiving and plain ratio would suit better.")
    print()

    rows = fetch_rows(args.limit)
    if not rows:
        return

    alerts = [r for r in rows if r.get("disruption_alert")]
    print(f"REAL DATA — {len(rows)} rows read, {len(alerts)} of them alerts")
    if len(alerts) < 20:
        print("Too few alert rows to read much into the numbers below; they are")
        print("reported for completeness, not as evidence.")

    # Group by day as a stand-in for the 30-minute window — the logged rows are
    # historical, so same-window clustering has to be approximated.
    by_day: dict[str, list[str]] = defaultdict(list)
    for r in alerts:
        day = (r.get("created_at") or "")[:10]
        by_day[day].append(norm(r.get("text", "")))

    print()
    print(f"{'thresh':<9}{'signals':<11}{'vs exact':<11}note")
    print("-" * 60)
    exact = sum(groups_at(v, 100) for v in by_day.values())
    for t in THRESHOLDS:
        n = sum(groups_at(v, t) for v in by_day.values())
        delta = n - exact
        print(f"{t:<9}{n:<11}{delta:+d}".ljust(31)
              + ("unchanged" if delta == 0 else f"{-delta} fewer signals than exact match"))
    print()
    print("A large drop means many logged reports are near-duplicates — which is")
    print("either spam the old rule counted twice, or genuine witnesses this rule")
    print("would now merge. Read a sample before trusting the number.")


if __name__ == "__main__":
    main()
