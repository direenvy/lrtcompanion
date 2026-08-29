"""
Augment minority classes (crowding, staff, aircon) using Gemini paraphrase generation.

Strategy:
  For each minority-class training row, ask Gemini to produce 5 paraphrases
  (English + Manglish/Bahasa mix to match real KL transit tweets).
  Filter for length, deduplicate, then append to training set.

Usage:
    cd D:/FYP
    python scripts/augment_with_gemini.py
"""
import sys, os, time, json
sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path
import pandas as pd
from collections import Counter
from dotenv import load_dotenv
import google.generativeai as genai

ROOT      = Path("D:/FYP")
# Start from previously-augmented file if it exists (so we keep crowding paraphrases)
_aug = ROOT / "data/nlp/final/train_augmented.csv"
TRAIN_CSV = _aug if _aug.exists() else ROOT / "data/nlp/final/train_labeled.csv"
OUT_CSV   = ROOT / "data/nlp/final/train_augmented.csv"
load_dotenv(ROOT / "backend/.env")

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel("models/gemini-flash-lite-latest")

# Target classes that performed poorly (0% F1 in last run)
TARGET_CLASSES = ["staff", "aircon"]  # crowding already augmented in previous run
PARAPHRASES_PER_ROW = 5
SLEEP_BETWEEN = 4.5  # ~13 req/min, under free-tier 15/min limit

train = pd.read_csv(TRAIN_CSV)
print(f"Loaded {len(train)} training rows")
print(f"Class counts: {dict(Counter(train['issue_type'].astype(str)))}")

new_rows = []

for cls in TARGET_CLASSES:
    rows = train[train["issue_type"] == cls]
    print(f"\nClass '{cls}': {len(rows)} rows → generating {PARAPHRASES_PER_ROW}× paraphrases")
    for i, (_, row) in enumerate(rows.iterrows(), 1):
        text = str(row["cleaned_text"])[:400]
        prompt = f"""You are augmenting training data for a Malaysian public-transit complaint classifier.

Original tweet (about: {cls}):
"{text}"

Generate exactly {PARAPHRASES_PER_ROW} paraphrases that:
- Keep the same meaning and the same complaint topic ({cls})
- Use natural KL English / Manglish / Bahasa Malaysia mix (like real Twitter)
- Vary wording, length, and tone
- Each on its own line, no numbering, no quotes, no extra commentary

Output only the {PARAPHRASES_PER_ROW} paraphrases, one per line."""
        for attempt in range(3):
            try:
                resp = model.generate_content(prompt)
                lines = [l.strip().lstrip("0123456789.-) ").strip()
                         for l in resp.text.strip().split("\n") if l.strip()]
                lines = [l for l in lines if 15 <= len(l) <= 400][:PARAPHRASES_PER_ROW]
                for p in lines:
                    new_rows.append({
                        "cleaned_text": p,
                        "sentiment":   row.get("sentiment", "negative"),
                        "issue_type":  cls,
                        "target_class": row.get("target_class", "positive"),
                        "lang":        row.get("lang", "en"),
                    })
                print(f"  [{i}/{len(rows)}] +{len(lines)} paraphrases")
                break
            except Exception as e:
                msg = str(e)
                if "429" in msg or "quota" in msg.lower():
                    wait = 55 if attempt == 0 else 30
                    print(f"  [{i}/{len(rows)}] rate-limited, sleeping {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"  [{i}/{len(rows)}] ERROR: {e}")
                    break
        time.sleep(SLEEP_BETWEEN)

print(f"\nGenerated {len(new_rows)} new rows")

# Build augmented train set
new_df = pd.DataFrame(new_rows)
# Align columns with original
for c in train.columns:
    if c not in new_df.columns:
        new_df[c] = ""
new_df = new_df[train.columns]

# Deduplicate
combined = pd.concat([train, new_df], ignore_index=True)
combined = combined.drop_duplicates(subset=["cleaned_text"], keep="first")

print(f"Train: {len(train)} → {len(combined)} rows after augmentation")
print(f"New class counts: {dict(Counter(combined['issue_type'].astype(str)))}")

combined.to_csv(OUT_CSV, index=False)
print(f"\nSaved → {OUT_CSV}")
print("Next: run scripts/train_with_smote.py with TRAIN_CSV pointed at train_augmented.csv")
