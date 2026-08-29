"""
Demo the source-trust hierarchy (Concept 1): a single anonymous tweet only
raises an UNCONFIRMED signal, but a single OFFICIAL @AskRapidKL announcement
CONFIRMS a disruption on its own.

Inserts two fresh alerts on two different lines so the Line Status board shows
the contrast side by side:
  • Sri Petaling (PH) — one anonymous tweet   -> 🟡 UNCONFIRMED (routing unchanged)
  • Kelana Jaya  (KJ) — one official post     -> 🔴 DISRUPTED   (routing avoids it)

Usage (from D:/FYP):
    python scripts/demo_official_confirm.py
    python scripts/demo_official_confirm.py --clear   # wipe the board first
"""
import sys, os, argparse
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")
from db.supabase_client import _get_client

# (text, sentiment, issue_type, minutes_ago, source)
ALERTS = [
    # One anonymous tweet naming the Sri Petaling line -> only "unconfirmed"
    ("Sri Petaling LRT rosak lagi ke ni, dah lama tak gerak",
        "negative", "breakdown", 3, "x_live"),
    # One OFFICIAL Rapid KL announcement on Kelana Jaya -> confirms instantly
    ("Perkhidmatan LRT Laluan Kelana Jaya terganggu berikutan gangguan teknikal. "
     "Bas gantian disediakan. Maaf atas kesulitan.",
        "negative", "breakdown", 2, "x_official"),
]

ap = argparse.ArgumentParser()
ap.add_argument("--clear", action="store_true", help="Delete existing rows first")
args = ap.parse_args()

sb = _get_client()
if sb is None:
    print("Supabase client not available — check backend/.env"); sys.exit(1)

if args.clear:
    sb.table("disruption_logs").delete().neq("id", 0).execute()
    print("Cleared disruption_logs table")

now = datetime.now(timezone.utc)
rows = [{
    "text": text, "sentiment": sent, "issue_type": issue,
    "disruption_alert": True, "source": source,
    "created_at": (now - timedelta(minutes=mins)).isoformat(),
} for text, sent, issue, mins, source in ALERTS]

result = sb.table("disruption_logs").insert(rows).execute()
print(f"Inserted {len(result.data)} demo alerts.\n")
print("Now open /status and you should see:")
print("  • Sri Petaling  -> 🟡 UNCONFIRMED  (1 tweet, weight 0.4 < 2.0)")
print("  • Kelana Jaya   -> 🔴 DISRUPTED    (1 official post, weight 2.0)")
print("    with a blue '✓ Official RapidKL' badge on the feed.\n")
print("Then plan KLCC -> Masjid Jamek: it will route around the KJ line,")
print("while Sri Petaling stays advisory — proving authority confirms alone.")
