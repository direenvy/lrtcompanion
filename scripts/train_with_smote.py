"""
Train issue_type & sentiment with SMOTE oversampling and compare to baseline.

Produces an ablation table:
    | Model      | Method   | Accuracy | macro-F1 |
Saves SMOTE-augmented model to backend/models/ if it beats baseline.

Usage:
    cd D:/FYP
    python scripts/train_with_smote.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path
import pandas as pd
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, accuracy_score, f1_score
from imblearn.over_sampling import SMOTE
from collections import Counter

ROOT      = Path("D:/FYP")
TRAIN_CSV = ROOT / "data/nlp/final/train_augmented.csv"  # was train_labeled.csv
TEST_CSV  = ROOT / "data/nlp/final/test_labeled.csv"
MODEL_DIR = ROOT / "data/nlp/outputs"

train = pd.read_csv(TRAIN_CSV)
test  = pd.read_csv(TEST_CSV)

print(f"Train: {len(train)} rows | Test: {len(test)} rows\n")

results = []

for target in ["sentiment", "issue_type"]:
    print(f"\n{'='*60}\nTarget: {target}\n{'='*60}")

    X_tr_text = train["cleaned_text"].astype(str)
    y_tr      = train[target].astype(str)
    X_te_text = test["cleaned_text"].astype(str)
    y_te      = test[target].astype(str)

    print(f"Train class distribution: {dict(Counter(y_tr))}")

    # Drop classes with <2 training samples (SMOTE needs ≥2 to compute neighbors)
    counts = Counter(y_tr)
    too_rare = {c for c, n in counts.items() if n < 2}
    if too_rare:
        print(f"Dropping rare classes (<2 samples): {too_rare}")
        keep = ~y_tr.isin(too_rare)
        X_tr_text = X_tr_text[keep].reset_index(drop=True)
        y_tr      = y_tr[keep].reset_index(drop=True)

    # ── Baseline (no SMOTE) ──────────────────────────────────────────────────
    vec = TfidfVectorizer(lowercase=True, ngram_range=(1,2),
                          min_df=1, max_features=10000, sublinear_tf=True)
    X_tr = vec.fit_transform(X_tr_text)
    X_te = vec.transform(X_te_text)

    base_clf = LogisticRegression(max_iter=2000, class_weight="balanced",
                                  C=1.0, random_state=42)
    base_clf.fit(X_tr, y_tr)
    y_pred_base = base_clf.predict(X_te)
    acc_base = accuracy_score(y_te, y_pred_base)
    f1_base  = f1_score(y_te, y_pred_base, average="macro", zero_division=0)
    print(f"\n--- Baseline ({target}) ---")
    print(f"Accuracy: {acc_base:.1%} | macro-F1: {f1_base:.3f}")
    print(classification_report(y_te, y_pred_base, zero_division=0))

    # ── SMOTE ────────────────────────────────────────────────────────────────
    # SMOTE k_neighbors must be < smallest class count
    smallest = min(Counter(y_tr).values())
    k = max(1, min(5, smallest - 1))
    try:
        smote = SMOTE(random_state=42, k_neighbors=k)
        X_tr_sm, y_tr_sm = smote.fit_resample(X_tr, y_tr)
        print(f"\nAfter SMOTE: {dict(Counter(y_tr_sm))}")

        sm_clf = LogisticRegression(max_iter=2000, C=1.0, random_state=42)
        sm_clf.fit(X_tr_sm, y_tr_sm)
        y_pred_sm = sm_clf.predict(X_te)
        acc_sm = accuracy_score(y_te, y_pred_sm)
        f1_sm  = f1_score(y_te, y_pred_sm, average="macro", zero_division=0)
        print(f"\n--- SMOTE ({target}) ---")
        print(f"Accuracy: {acc_sm:.1%} | macro-F1: {f1_sm:.3f}")
        print(classification_report(y_te, y_pred_sm, zero_division=0))
    except Exception as e:
        print(f"SMOTE failed: {e}")
        acc_sm, f1_sm = 0.0, 0.0
        sm_clf = None

    results.append({
        "target": target,
        "baseline_acc": acc_base, "baseline_f1": f1_base,
        "smote_acc":    acc_sm,   "smote_f1":    f1_sm,
    })

    # ── Save winner ──────────────────────────────────────────────────────────
    if sm_clf is not None and f1_sm > f1_base:
        # Wrap as pipeline-compatible: save vec + clf as a single pipeline
        from sklearn.pipeline import Pipeline
        winner = Pipeline([("tfidf", vec), ("clf", sm_clf)])
        tag = "SMOTE"
    else:
        from sklearn.pipeline import Pipeline
        winner = Pipeline([("tfidf", vec), ("clf", base_clf)])
        tag = "baseline"

    out = MODEL_DIR / target / f"{target}_baseline.joblib"
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(winner, out)
    bk = ROOT / "backend/models" / f"{target}_baseline.joblib"
    bk.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(winner, bk)
    print(f"\nSaved winner ({tag}) → {out}")

# ── Ablation table ──────────────────────────────────────────────────────────
print(f"\n{'='*60}\nABLATION TABLE\n{'='*60}")
print(f"{'Target':<14}{'Method':<12}{'Accuracy':<12}{'macro-F1':<10}")
print("-" * 48)
for r in results:
    print(f"{r['target']:<14}{'Baseline':<12}{r['baseline_acc']:<12.1%}{r['baseline_f1']:<10.3f}")
    print(f"{r['target']:<14}{'SMOTE':<12}{r['smote_acc']:<12.1%}{r['smote_f1']:<10.3f}")
print("\nDone. Restart the FastAPI backend to load new models.")
