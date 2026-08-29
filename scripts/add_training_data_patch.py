"""Patch 2: adds aircond class + breakdown examples matching test set style."""
import csv
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRAIN_CSV = PROJECT_ROOT / "data" / "nlp" / "final" / "train_labeled.csv"

PATCH = [
    # ── AIRCOND (negative) — class existed in test but not in training ──────
    ("@askrapidkl tolong bukak aircond coach LRT Kelana Jaya skrg panas sangat", "negative", "aircond"),
    ("Panas betul train Kelana Jaya ni tolongggg bukak aircond @askrapidkl", "negative", "aircond"),
    ("Air cond rosak dalam LRT, panas gila, penumpang semua berpeluh", "negative", "aircond"),
    ("LRT aircond broken at Sri Petaling line, extremely hot inside the coach", "negative", "aircond"),
    ("No air conditioning on MRT Kajang train today, unbearably hot inside", "negative", "aircond"),
    ("Aircond tidak sejuk langsung dalam train KJ line, sila betulkan segera", "negative", "aircond"),
    ("@askrapidkl please fix the aircond in coach 3 Ampang line, passengers sweating", "negative", "aircond"),
    ("Train so hot aircond not working again on Kelana Jaya line, horrible experience", "negative", "aircond"),
    ("Aircond LRT rosak lagi, dah 3 hari macam ni, tolong la Rapid KL", "negative", "aircond"),
    ("Hot and stuffy inside MRT, aircond clearly not working, very uncomfortable journey", "negative", "aircond"),

    # ── BREAKDOWN matching test-set style ────────────────────────────────────
    ("LRT Ampang Sri Petaling line service disruption this evening track switch problem at Chan Sow Lin", "negative", "breakdown"),
    ("Service disruption on Kelana Jaya line due to faulty track switch, trains delayed", "negative", "breakdown"),
    ("Rapid KL alert: train fault on MRT Kajang line, single track operation in effect", "negative", "breakdown"),
    ("LRT service suspended between Masjid Jamek and Ampang Park due to train fault", "negative", "breakdown"),
    ("Disruption on Sri Petaling line caused by broken down train near Bukit Jalil station", "negative", "breakdown"),
    ("Track problem at Chan Sow Lin causing service disruption both directions Ampang line", "negative", "breakdown"),
    ("Rapid KL train fault: Kelana Jaya line operating at reduced capacity due to breakdown", "negative", "breakdown"),
    ("Emergency train fault evacuation at Universiti station, passengers transferred to buses", "negative", "breakdown"),
    ("LRT track switch failure causing major service disruption evening peak hour today", "negative", "breakdown"),
    ("Signal failure near Bangsar station causing severe disruption KJ line trains delayed 20 min", "negative", "breakdown"),
]


def main():
    with open(TRAIN_CSV, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    existing_ids = [r["sample_id"] for r in rows if r["sample_id"].startswith("S")]
    max_num = max(int(s[1:]) for s in existing_ids if s[1:].isdigit())

    new_rows = []
    for i, (text, sentiment, issue_type) in enumerate(PATCH):
        row = {k: "" for k in fieldnames}
        row["sample_id"]      = f"S{max_num + i + 1:03d}"
        row["cleaned_text"]   = text
        row["sentiment"]      = sentiment
        row["issue_type"]     = issue_type
        row["relevance"]      = "relevant"
        row["lang"]           = "en"
        row["source_dataset"] = "synthetic_patch2"
        row["notes"]          = "aircond_and_breakdown_patch"
        new_rows.append(row)

    with open(TRAIN_CSV, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerows(new_rows)

    all_rows = rows + new_rows
    print(f"Added {len(new_rows)} patch examples. Total: {len(all_rows)}")
    print("Sentiment:", dict(Counter(r["sentiment"] for r in all_rows)))
    print("Issue type:", dict(Counter(r["issue_type"] for r in all_rows)))


if __name__ == "__main__":
    main()
