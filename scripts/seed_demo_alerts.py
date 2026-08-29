"""
Seed Supabase `disruption_logs` with realistic alerts so the Line Status board
and Dashboard look alive when an examiner opens the app.

Inserts ~6 alerts spread across the last 4 hours, hitting multiple lines and
mixing recent (red) + older (amber) so the board shows a mix of statuses.

Usage (from D:/FYP):
    python scripts/seed_demo_alerts.py
    python scripts/seed_demo_alerts.py --clear   # wipe first
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
    ("MRT Kajang stuck between Pasar Seni and Muzium Negara, no announcement yet 😡",
        "negative", "breakdown", 10, "user"),
    ("LRT Kelana Jaya line packed like sardines, can't even board at KLCC",
        "negative", "crowding", 18, "user"),
    ("LRT3 breakdown at Johan Setia, shah alam line trains held at platform",
        "negative", "breakdown", 25, "x_live"),
    ("Ampang line train delayed almost 25 minutes at Bandar Tasik Selatan",
        "negative", "delay", 45, "user"),
    ("Monorail aircond not working again, panas gila inside the cabin",
        "negative", "aircon", 75, "x_live"),
    ("Staff at MRT Putrajaya counter very rude, refused to explain the delay",
        "negative", "staff", 150, "user"),
    ("Sri Petaling LRT had a power trip earlier, services resumed now",
        "neutral", "breakdown", 220, "user"),
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
rows = []
for text, sent, issue, mins, source in ALERTS:
    rows.append({
        "text":              text,
        "sentiment":         sent,
        "issue_type":        issue,
        "disruption_alert":  True,
        "source":            source,
        "created_at":        (now - timedelta(minutes=mins)).isoformat(),
    })

result = sb.table("disruption_logs").insert(rows).execute()
print(f"Inserted {len(result.data)} demo alerts spanning the last 4 hours:")
for r in result.data:
    print(f"  • [{r['issue_type']:<9}] {r['text'][:70]}")

print("\nDone. Refresh /status to see the board light up.")
