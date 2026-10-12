"""
Adversarial evaluation of the RAG grounding checker.

The unit tests in backend/tests/test_rag_grounding.py prove the WIRING — that a
verdict of "unsupported" becomes a refusal. They say nothing about whether the
checker is any good: a verifier that always answers "supported" passes every
one of them.

This script tests the JUDGE. It feeds _verify_grounded twelve answers whose
correct verdict is known in advance — half faithful to the sources, half
deliberately wrong — and reports what it caught. Several of the wrong answers
are SUBTLE (a changed number, a plausible invented detail) because a checker
that only catches obvious contradictions is not doing the job.

Needs a real GEMINI_API_KEY; it makes one API call per case.

    cd D:/FYP
    python scripts/verify_grounding_eval.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from agents.rag_agent import _verify_grounded  # noqa: E402


FARE = [{"text": "KLCC to Ampang: RM4.20 cash, RM3.70 cashless. Fares are "
                 "cheaper when paying with a Touch 'n Go or bank card.",
         "source_file": "integrated_fares.csv"}]

MY50 = [{"text": "The My50 monthly pass costs RM50 and gives unlimited travel "
                 "for 30 consecutive days on Rapid KL rail and bus services.",
         "source_file": "my50_faq.pdf"}]

HOURS = [{"text": "LRT Kelana Jaya Line operates from 6:00 am to 11:45 pm daily. "
                  "Last trains depart terminal stations at 11:30 pm.",
          "source_file": "operating_hours.pdf"}]

LIFT = [{"text": "Passengers requiring step-free access should use the lift at "
                 "the concourse level. Report a faulty lift to station staff.",
         "source_file": "accessibility_sop.pdf"}]


# (label, chunks, answer, expected_verdict, why it is here)
CASES = [
    # ---- faithful: must NOT be refused ----
    ("exact quote", FARE,
     "KLCC to Ampang costs **RM4.20 cash / RM3.70 cashless**.",
     "supported", "verbatim figures"),
    ("paraphrase", MY50,
     "The My50 pass is **RM50** a month and lets you travel as much as you like for 30 days.",
     "supported", "reworded but faithful — must not be punished for wording"),
    ("partial extract", HOURS,
     "The Kelana Jaya Line runs from **6:00 am to 11:45 pm**.",
     "supported", "answers less than the source says, but nothing false"),
    ("formatting noise", FARE,
     "Sure! 😊 KLCC to Ampang is **RM4.20** cash. Hope that helps!",
     "supported", "politeness and emoji are not claims"),
    ("safe advice", LIFT,
     "Use the lift at concourse level, and tell station staff if it is out of order.",
     "supported", "restates the SOP"),
    ("units reworded", MY50,
     "It costs fifty ringgit and runs for a month.",
     "supported", "same facts in words rather than digits"),

    # ---- wrong: MUST be caught ----
    ("wrong price", FARE,
     "KLCC to Ampang costs **RM8.40 cash**.",
     "unsupported", "doubled the fare — the obvious case"),
    ("swapped cash/cashless", FARE,
     "KLCC to Ampang is **RM3.70 cash / RM4.20 cashless**.",
     "unsupported", "SUBTLE: both numbers appear, assigned the wrong way round"),
    ("changed duration", MY50,
     "The My50 pass costs **RM50** and is valid for **60 days**.",
     "unsupported", "SUBTLE: price right, duration wrong — a partial check would miss it"),
    ("invented detail", MY50,
     "The My50 pass costs **RM50**. Students get an additional 50% discount.",
     "unsupported", "SUBTLE: plausible, absent from the source"),
    ("invented hours", HOURS,
     "The Kelana Jaya Line runs **24 hours** on weekends.",
     "unsupported", "contradicts the source"),
    ("off-topic", FARE,
     "The capital of France is Paris.",
     "unsupported", "nothing to do with the retrieved context"),
]


def main():
    print(f"{'case':<22}{'expected':<14}{'got':<14}{'ok':<5}note")
    print("-" * 96)
    hits = misses = 0
    false_alarms = 0
    for label, chunks, ans, expected, note in CASES:
        got = _verify_grounded(ans, chunks)["verdict"]
        # Mirror what the system actually DOES: both verdicts refuse. Counting
        # 'partial' as a catch while the code served it was how this script
        # flattered the checker in its first run.
        caught = got in ("unsupported", "partial")
        ok = (expected == "supported" and got == "supported") or \
             (expected == "unsupported" and caught)
        if expected == "unsupported":
            hits += ok
            misses += (not ok)
        else:
            false_alarms += (not ok)
        print(f"{label:<22}{expected:<14}{got:<14}{'yes' if ok else 'NO':<5}{note}")

    total_bad = sum(1 for c in CASES if c[3] == "unsupported")
    total_good = len(CASES) - total_bad
    print("-" * 96)
    print(f"caught {hits}/{total_bad} wrong answers   ·   "
          f"{false_alarms}/{total_good} good answers wrongly flagged")
    print("(both 'unsupported' and 'partial' refuse in the deployed path)")
    print()
    if hits == 0:
        print("The checker caught nothing. It is not working — do not ship it.")
    elif misses:
        print(f"Missed {misses}. Look at which: if the subtle ones slipped through,")
        print("the prompt needs to insist on checking every number and detail.")
    if false_alarms:
        print(f"{false_alarms} faithful answer(s) flagged. Too strict — it is probably")
        print("demanding literal word overlap rather than entailment.")
    if hits == total_bad and not false_alarms:
        print("Clean sweep on this set. Worth extending with your own cases before")
        print("claiming the checker is reliable — twelve examples is a smoke test,")
        print("not an evaluation.")


if __name__ == "__main__":
    main()
