"""
Adversarial evaluation of the RAG grounding checker.

The unit tests in backend/tests/test_rag_grounding.py prove the WIRING — that a
bad verdict becomes a refusal. They say nothing about whether the checker is any
good: a verifier that always answers "supported" passes every one of them.

This script tests the JUDGE. It feeds _verify_grounded answers whose correct
verdict is known in advance — half faithful to the sources, half deliberately
wrong — and reports what it caught.

Two things make it worth trusting:

  * The SOURCES are real. Every chunk below is pasted verbatim from
    data/rag/outputs/chunked_documents.jsonl, so the checker is judged against
    the text it actually sees in production, not against prose written to be
    easy.

  * The WRONG answers are mostly subtle. Doubling a price is trivial to catch.
    What matters is a correct price beside a changed duration, a plausible
    invented eligibility rule, or a fact borrowed from a neighbouring product —
    the errors a fluent model actually makes.

A 'partial' verdict counts as caught, because the deployed path refuses on
partial as well as unsupported.

Needs a real GEMINI_API_KEY; one API call per case.

    cd D:/FYP
    python scripts/verify_grounding_eval.py
    python scripts/verify_grounding_eval.py --only fares
"""
import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from agents.rag_agent import _verify_grounded  # noqa: E402


# ─── sources: verbatim from the corpus ───────────────────────────────────────

MY50 = [{"source_file": "ENG-MY50-and-MUTIARA-PASS-FAQ-MyKad-or-MyTentera.pdf", "text":
    "1. What is My50 Pass? My50 is an unlimited travel pass that offers 30 days unlimited "
    "rides on Rapid KL LRT, MRT, Monorail, BRT, Rapid KL bus and MRT feeder bus services in "
    "Klang Valley. For Pulau Pinang, My50 is called Mutiara Pass that offers 30 days unlimited "
    "rides for all Malaysians on Rapid Penang bus services. 2. What are the eligibility criteria "
    "to purchase My50? You must be a Malaysian citizen with a valid MyKad or MyTentera. "
    "3. What is the price of My50? The price for a My50 pass is RM50."}]

MY50_RULES = [{"source_file": "ENG-My50-DIGITAL-TRAVEL-PASS-DEC-2025.pdf", "text":
    "Passes bought via Rapid KL Customer Service Counters are typically linked to your MyKad, "
    "not to your Enhanced NFC-enabled TNG card — which is why they won't be visible in the TNG "
    "eWallet. 6. Will I be charged SST (Sales and Service Tax) when purchasing the My50 Pass? "
    "No. The My50 Pass is exempted from SST. 7. Can I pause or extend my My50 Pass if I don't "
    "use it? No. Once activated, the My50 Pass runs on a continuous 30-day cycle. It cannot be "
    "paused, extended, or carried forward. Even if unused, the validity period continues."}]

BULANAN = [{"source_file": "ENG-RAPID-BULANAN-FAQ-DEC-2025.pdf", "text":
    "What is the difference between Rapid Bulanan and My50 Pass for Malaysians? My50 Pass will "
    "remain available exclusively to Malaysians with a valid MyKad or MyTentera, offering "
    "unlimited travel for 30 days at RM50. For non-Malaysian and the general public, Rapid "
    "Bulanan provides an unlimited 30-day travel at RM150."}]

FARE = [{"source_file": "integrated_fare_table.txt", "text":
    "KLCC to Ampang: RM4.20 cash, RM3.70 cashless. Fares shown are for the integrated network "
    "covering LRT Kelana Jaya, LRT Ampang and Sri Petaling, Monorail, BRT, MRT Kajang and MRT "
    "Putrajaya. Cashless fares apply when paying with a Touch 'n Go card or supported bank card."}]

SAL = [{"source_file": "lrt3_fare_table.txt", "text":
    "LRT3 Shah Alam Line fares are charged separately from the integrated network. A journey "
    "combining the Shah Alam Line with the integrated network pays both fares, joined at "
    "Bandar Utama."}]


# ─── cases: (category, label, chunks, answer, expected, why it is here) ───────

CASES = [
    # ───── faithful: must NOT be refused ─────
    ("passes", "exact price", MY50,
     "The My50 pass costs **RM50**.",
     "supported", "verbatim figure"),
    ("passes", "paraphrase", MY50,
     "It's **RM50** a month and you can ride as much as you like for 30 days.",
     "supported", "reworded, faithful — must not be punished for wording"),
    ("passes", "subset of the source", MY50,
     "My50 covers LRT, MRT and Monorail in the Klang Valley.",
     "supported", "says less than the source, nothing false"),
    ("passes", "eligibility stated", MY50,
     "You need to be a Malaysian citizen with a MyKad or MyTentera.",
     "supported", "directly in the source"),
    ("passes", "two facts joined", MY50,
     "**RM50** for 30 days of unlimited rides, for Malaysians with a MyKad.",
     "supported", "combines two supported claims"),
    ("rules", "no-pause rule", MY50_RULES,
     "No — once activated it runs for 30 continuous days and can't be paused or extended.",
     "supported", "restates the rule"),
    ("rules", "SST answer", MY50_RULES,
     "No, the My50 Pass is **exempt from SST**.",
     "supported", "verbatim"),
    ("rules", "explains the TNG case", MY50_RULES,
     "If you bought it at a counter it's linked to your MyKad, so it won't show in the TNG eWallet.",
     "supported", "paraphrase of a slightly technical passage"),
    ("fares", "exact fare", FARE,
     "KLCC to Ampang costs **RM4.20 cash / RM3.70 cashless**.",
     "supported", "verbatim figures"),
    ("fares", "cashless explained", FARE,
     "Cashless means a Touch 'n Go card or a supported bank card, and it's cheaper.",
     "supported", "paraphrase"),
    ("fares", "formatting noise", FARE,
     "Sure! 😊 That's **RM4.20** by cash. Hope this helps!",
     "supported", "politeness and emoji are not claims"),
    ("fares", "SAL separate fares", SAL,
     "The Shah Alam Line is charged separately — a combined trip pays both fares.",
     "supported", "restates the rule"),
    ("compare", "both products, correct", BULANAN,
     "My50 is **RM50** for Malaysians; Rapid Bulanan is **RM150** for everyone else.",
     "supported", "both figures correct and correctly assigned"),
    ("compare", "one side only", BULANAN,
     "Rapid Bulanan gives 30 days of unlimited travel for **RM150**.",
     "supported", "answers half the source, accurately"),

    # ───── wrong: MUST be caught ─────
    ("passes", "doubled price", MY50,
     "The My50 pass costs **RM100**.",
     "unsupported", "obvious — the control case"),
    ("passes", "changed duration", MY50,
     "The My50 pass costs **RM50** and is valid for **60 days**.",
     "unsupported", "SUBTLE: price right, duration wrong"),
    ("passes", "invented discount", MY50,
     "The My50 pass costs **RM50**. Students receive an additional 50% discount.",
     "unsupported", "SUBTLE: plausible, absent from source"),
    ("passes", "loosened eligibility", MY50,
     "Anyone can buy a My50 pass, including tourists and foreign workers.",
     "unsupported", "contradicts the MyKad/MyTentera requirement"),
    ("passes", "wrong region", MY50,
     "My50 gives unlimited rides on Rapid Penang buses in the Klang Valley.",
     "unsupported", "SUBTLE: conflates My50 with Mutiara Pass"),
    ("passes", "invented mode", MY50,
     "My50 covers LRT, MRT, Monorail and **KTM Komuter** services.",
     "unsupported", "SUBTLE: one extra mode slipped into a correct list"),
    ("rules", "reversed the rule", MY50_RULES,
     "Yes, you can pause your My50 Pass and resume it later.",
     "unsupported", "directly contradicts the source"),
    ("rules", "invented tax", MY50_RULES,
     "The My50 Pass costs RM50 plus **6% SST**.",
     "unsupported", "SUBTLE: inverts the exemption into a charge"),
    ("rules", "invented grace period", MY50_RULES,
     "Once activated it runs 30 days, with a 7-day grace period if unused.",
     "unsupported", "SUBTLE: plausible-sounding addition the source denies"),
    ("fares", "swapped cash/cashless", FARE,
     "KLCC to Ampang is **RM3.70 cash / RM4.20 cashless**.",
     "unsupported", "SUBTLE: both numbers present, assigned the wrong way round"),
    ("fares", "wrong fare", FARE,
     "KLCC to Ampang costs **RM8.40 cash**.",
     "unsupported", "doubled"),
    ("fares", "invented concession", FARE,
     "KLCC to Ampang is RM4.20, or RM2.10 with a senior citizen card.",
     "unsupported", "SUBTLE: correct base fare, invented concession"),
    ("fares", "overgeneralised", SAL,
     "All Rapid KL lines including the Shah Alam Line share one integrated fare.",
     "unsupported", "contradicts the separate-fare rule"),
    ("compare", "swapped prices", BULANAN,
     "My50 is **RM150** and Rapid Bulanan is **RM50**.",
     "unsupported", "SUBTLE: both figures present, swapped between products"),
    ("compare", "wrong eligibility", BULANAN,
     "Rapid Bulanan at **RM150** is available only to Malaysians with a MyKad.",
     "unsupported", "SUBTLE: price right, eligibility taken from the other product"),
    ("offtopic", "unrelated fact", FARE,
     "The capital of France is Paris.",
     "unsupported", "nothing to do with the context"),
    ("offtopic", "plausible but absent", MY50,
     "You can buy a My50 pass at any 7-Eleven store.",
     "unsupported", "SUBTLE: sounds like a transit fact, no source for it"),
    ("offtopic", "hedged invention", MY50_RULES,
     "I believe the pass can usually be refunded within 14 days of purchase.",
     "unsupported", "SUBTLE: hedging does not make an unsourced claim acceptable"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="run one category: "
                    + ", ".join(sorted({c[0] for c in CASES})))
    # Free-tier Gemini is rate-limited per minute. Firing 30+ calls back to back
    # exhausts it and returns 'unchecked' for the rest, which looks exactly like
    # a checker that missed everything. Pace the calls instead.
    ap.add_argument("--delay", type=float, default=4.5,
                    help="seconds between calls (default 4.5, ~13/min)")
    args = ap.parse_args()
    cases = [c for c in CASES if not args.only or c[0] == args.only]
    if not cases:
        print(f"no cases in category {args.only!r}")
        return

    print(f"{'cat':<9}{'case':<24}{'expected':<13}{'got':<13}{'ok':<5}note")
    print("-" * 104)

    hits = misses = false_alarms = unchecked = 0
    missed_cases, flagged_cases = [], []
    by_cat = {}

    for i, (cat, label, chunks, ans, expected, note) in enumerate(cases):
        if i:
            time.sleep(args.delay)
        got = _verify_grounded(ans, chunks)["verdict"]
        if got == "unchecked":                 # rate limit — one retry, longer pause
            time.sleep(args.delay * 4)
            got = _verify_grounded(ans, chunks)["verdict"]
        if got == "unchecked":
            unchecked += 1
            print(f"{cat:<9}{label:<24}{expected:<13}{'unchecked':<13}{'--':<5}"
                  f"NOT EVALUATED (rate limit or verify timeout)")
            continue
        caught = got in ("unsupported", "partial")       # both refuse in production
        ok = (expected == "supported" and got == "supported") or \
             (expected == "unsupported" and caught)
        if expected == "unsupported":
            hits += ok
            misses += (not ok)
            if not ok:
                missed_cases.append(f"{cat}/{label}")
        else:
            false_alarms += (not ok)
            if not ok:
                flagged_cases.append(f"{cat}/{label}")
        tally = by_cat.setdefault(cat, Counter())
        tally["n"] += 1
        tally["ok"] += ok
        print(f"{cat:<9}{label:<24}{expected:<13}{got:<13}{'yes' if ok else 'NO':<5}{note}")

    # Only count cases the checker actually judged — an unchecked case is a
    # call that never happened, not a verdict it got wrong.
    bad = hits + misses
    good = len(cases) - bad - unchecked
    subtle = [c for c in cases if c[4] == "unsupported" and c[5].startswith("SUBTLE")]
    subtle_missed = [m for m in missed_cases
                     if any(f"{c[0]}/{c[1]}" == m for c in subtle)]

    print("-" * 104)
    if unchecked:
        print(f"!! {unchecked} case(s) NOT EVALUATED — rate limited. Rerun with a")
        print(f"   larger --delay, or in category batches (--only fares).")
        print()
    print(f"caught {hits}/{bad} wrong answers   ·   "
          f"{false_alarms}/{good} faithful answers wrongly refused   ·   "
          f"subtle missed: {len(subtle_missed)}/{len(subtle)}")
    print("by category: " + "  ".join(
        f"{k} {v['ok']}/{v['n']}" for k, v in sorted(by_cat.items())))
    print("(both 'unsupported' and 'partial' refuse in the deployed path)")
    print()

    if bad == 0 and good == 0:
        print("Nothing was evaluated — every call was rate limited. This result says")
        print("nothing about the checker. Wait for quota to reset and rerun.")
        return
    if bad and hits == 0:
        print("The checker caught nothing it was asked to judge. Do not ship it.")
    if missed_cases:
        print(f"MISSED: {', '.join(missed_cases)}")
        print("  If these are the subtle ones, the prompt needs to insist that every")
        print("  number, duration, product name and eligibility rule be checked")
        print("  individually, not just the headline claim.")
    if flagged_cases:
        print(f"WRONGLY REFUSED: {', '.join(flagged_cases)}")
        print("  Too strict — it is probably demanding literal word overlap rather")
        print("  than entailment. Loosen the 'judge meaning, not wording' line.")
    if bad and hits == bad and not false_alarms:
        print("Clean sweep. Note what that does and does not license: it means the")
        print("checker handles these failure modes, not that it handles all of them.")
        print("Add cases from real refusals as they appear in the logs.")


if __name__ == "__main__":
    main()
