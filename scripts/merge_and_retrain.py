"""
Merge newly labeled batch into train/test sets, then retrain both NLP models.

Usage (after labeling LABEL_THIS_BATCH1.csv):
    cd D:/FYP
    python scripts/merge_and_retrain.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path
import pandas as pd
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, accuracy_score
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split

ROOT      = Path("D:/FYP")
BATCH_CSV = ROOT / "data/nlp/interim/LABEL_THIS_BATCH1.csv"
# Part C live-labelling: python scripts/merge_and_retrain.py --batch data/nlp/interim/live_x_labelling.csv
if "--batch" in sys.argv:
    BATCH_CSV = Path(sys.argv[sys.argv.index("--batch") + 1])
    if not BATCH_CSV.is_absolute():
        BATCH_CSV = ROOT / BATCH_CSV
TRAIN_CSV = ROOT / "data/nlp/final/train_labeled.csv"
TEST_CSV  = ROOT / "data/nlp/final/test_labeled.csv"
MODEL_DIR = ROOT / "data/nlp/outputs"

# ── 1. Load new batch ─────────────────────────────────────────────────────────
batch = pd.read_csv(BATCH_CSV)
new   = batch[
    batch["sentiment"].notna() & batch["sentiment"].astype(str).str.strip().ne("") &
    batch["issue_type"].notna() & batch["issue_type"].astype(str).str.strip().ne("")
].copy()
new["sentiment"]  = new["sentiment"].str.strip().str.lower()
new["issue_type"] = new["issue_type"].str.strip().str.lower()

print(f"New labeled posts: {len(new)}")
print("Sentiment:"); print(new["sentiment"].value_counts().to_string())
print("Issue type:"); print(new["issue_type"].value_counts().to_string())

if len(new) == 0:
    print("\nNo labeled rows found — fill in sentiment/issue_type columns first.")
    sys.exit(1)

# ── 2. Split 80/20 into train/test ────────────────────────────────────────────
try:
    tr_new, te_new = train_test_split(
        new, test_size=0.2, stratify=new["issue_type"], random_state=42)
except ValueError:
    tr_new, te_new = train_test_split(new, test_size=0.2, random_state=42)

# ── 3. Append to existing files ───────────────────────────────────────────────
train_old = pd.read_csv(TRAIN_CSV)
test_old  = pd.read_csv(TEST_CSV)
needed    = list(train_old.columns)

def align(df, cols):
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols]

existing = set(train_old["cleaned_text"].str.strip())
tr_new   = align(tr_new.copy(), needed)
te_new   = align(te_new.copy(), needed)
tr_new   = tr_new[~tr_new["cleaned_text"].str.strip().isin(existing)]

train_new = pd.concat([train_old, tr_new], ignore_index=True)
test_new  = pd.concat([test_old,  te_new], ignore_index=True)
train_new.to_csv(TRAIN_CSV, index=False)
test_new.to_csv(TEST_CSV,   index=False)

print(f"\nTrain: {len(train_old)} → {len(train_new)} rows")
print(f"Test:  {len(test_old)}  → {len(test_new)} rows")

# ── 4. Retrain ────────────────────────────────────────────────────────────────
for target, C in [("sentiment", 1.0), ("issue_type", 1.0)]:
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(
            lowercase=True, ngram_range=(1, 2),
            min_df=1, max_features=10000, sublinear_tf=True)),
        ("clf", LogisticRegression(
            max_iter=2000, class_weight="balanced",
            C=C, random_state=42)),
    ])
    X_tr = train_new["cleaned_text"].astype(str)
    y_tr = train_new[target].astype(str)
    X_te = test_new["cleaned_text"].astype(str)
    y_te = test_new[target].astype(str)
    pipe.fit(X_tr, y_tr)
    y_pred = pipe.predict(X_te)
    acc = accuracy_score(y_te, y_pred)
    print(f"\n=== {target} — {acc:.1%} ===")
    print(classification_report(y_te, y_pred, zero_division=0))
    out = MODEL_DIR / target / f"{target}_baseline.joblib"
    joblib.dump(pipe, out)
    # Also update backend/models copy
    bk = ROOT / "backend/models" / f"{target}_baseline.joblib"
    joblib.dump(pipe, bk)
    print(f"Saved → {out}")

print("\nDone! Restart the FastAPI backend to load new models.")
