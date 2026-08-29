"""
Hyperparameter search for the issue-type model — HONEST protocol:
configurations are ranked by 5-fold cross-validated macro-F1 on the TRAINING
set only; the single best config is then evaluated ONCE on the held-out test
set. The test set is never used for selection.

Usage:
    cd D:/FYP
    python scripts/tune_issue_model.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path
import pandas as pd
import numpy as np
from collections import Counter
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, accuracy_score, f1_score
from sklearn.model_selection import StratifiedKFold
from imblearn.over_sampling import SMOTE

ROOT      = Path("D:/FYP")
TRAIN_CSV = ROOT / "data/nlp/final/train_augmented.csv"
TEST_CSV  = ROOT / "data/nlp/final/test_labeled.csv"

train = pd.read_csv(TRAIN_CSV)
test  = pd.read_csv(TEST_CSV)
X_text = train["cleaned_text"].astype(str).values
y      = train["issue_type"].astype(str).values

GRID = []
for ngram in [(1, 2), (1, 3)]:
    for min_df in [1, 2]:
        for C in [0.5, 1.0, 2.0, 4.0]:
            for use_smote in [False, True]:
                GRID.append({"ngram": ngram, "min_df": min_df, "C": C, "smote": use_smote})

def build_vec(cfg):
    return TfidfVectorizer(lowercase=True, ngram_range=cfg["ngram"],
                           min_df=cfg["min_df"], max_features=10000,
                           sublinear_tf=True)

def fit_predict(cfg, Xtr_text, ytr, Xte_text):
    vec = build_vec(cfg)
    Xtr = vec.fit_transform(Xtr_text)
    Xte = vec.transform(Xte_text)
    if cfg["smote"]:
        k = max(1, min(5, min(Counter(ytr).values()) - 1))
        Xtr, ytr = SMOTE(random_state=42, k_neighbors=k).fit_resample(Xtr, ytr)
        clf = LogisticRegression(max_iter=2000, C=cfg["C"], random_state=42)
    else:
        clf = LogisticRegression(max_iter=2000, C=cfg["C"],
                                 class_weight="balanced", random_state=42)
    clf.fit(Xtr, ytr)
    return vec, clf, clf.predict(Xte)

# ── CV selection on train only ────────────────────────────────────────────────
skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
print(f"Grid: {len(GRID)} configs × 5 folds")
scores = []
for cfg in GRID:
    fold_f1 = []
    for tr_idx, va_idx in skf.split(X_text, y):
        _, _, pred = fit_predict(cfg, X_text[tr_idx], y[tr_idx], X_text[va_idx])
        fold_f1.append(f1_score(y[va_idx], pred, average="macro", zero_division=0))
    scores.append((np.mean(fold_f1), cfg))
    print(f"  cv-macroF1={np.mean(fold_f1):.3f}  {cfg}")

scores.sort(key=lambda s: s[0], reverse=True)
best_cv, best = scores[0]
print(f"\nBest by CV: {best} (cv-macroF1 {best_cv:.3f})")

# ── Single test evaluation of the CV winner ───────────────────────────────────
vec, clf, y_pred = fit_predict(best, X_text, y,
                               test["cleaned_text"].astype(str).values)
y_te = test["issue_type"].astype(str).values
acc = accuracy_score(y_te, y_pred)
f1  = f1_score(y_te, y_pred, average="macro", zero_division=0)
print(f"\n=== TEST (evaluated once) === accuracy {acc:.1%} | macro-F1 {f1:.3f}")
print(classification_report(y_te, y_pred, zero_division=0))

# ── Save only if it beats the current deployed numbers on macro-F1 ────────────
if "--save" in sys.argv:
    import joblib
    from sklearn.pipeline import Pipeline
    winner = Pipeline([("tfidf", vec), ("clf", clf)])
    for out in [ROOT / "data/nlp/outputs/issue_type/issue_type_baseline.joblib",
                ROOT / "backend/models/issue_type_baseline.joblib"]:
        out.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(winner, out)
        print(f"Saved → {out}")
