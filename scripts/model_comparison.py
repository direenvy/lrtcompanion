"""
Presentation-ready model comparison — justify the choice of Logistic Regression.

Trains four candidate classifiers on the SAME TF-IDF features and the SAME
573/102 split (SMOTE on the training fold only) and reports accuracy and
macro-F1 on the held-out test set for both targets. Read-only: never touches
the shipped models.

Output -> D:/FYP-materials/figure-scripts/model_comparison.png

Usage:  python scripts/model_comparison.py
"""
import sys
from pathlib import Path
from collections import Counter

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.svm import LinearSVC
from sklearn.naive_bayes import MultinomialNB
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from imblearn.over_sampling import SMOTE

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path("D:/FYP")
OUT  = Path("D:/FYP-materials/figure-scripts")
OUT.mkdir(parents=True, exist_ok=True)

train = pd.read_csv(ROOT / "data/nlp/final/train_augmented.csv")
test  = pd.read_csv(ROOT / "data/nlp/final/test_labeled.csv")

MODELS = {
    "Logistic Regression": lambda: LogisticRegression(max_iter=2000, C=1.0, random_state=42),
    "Linear SVM":          lambda: LinearSVC(C=1.0, random_state=42),
    "Naive Bayes":         lambda: MultinomialNB(),
    "Random Forest":       lambda: RandomForestClassifier(n_estimators=300, random_state=42),
}

# vivid palette; shipped model (LR) gets the strong brand blue
BLUE, RED, GREEN, ORANGE = "#2E86DE", "#EE5253", "#10AC84", "#F79F1F"
BARCOLORS = [BLUE, RED, GREEN, ORANGE]
INK, GRID = "#1A202C", "#E2E8F0"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 12,
    "axes.edgecolor": "#CBD5E0", "text.color": INK, "xtick.color": INK,
    "ytick.color": INK, "savefig.facecolor": "white", "axes.facecolor": "white",
    "figure.facecolor": "white", "axes.titleweight": "bold", "axes.titlesize": 14,
    "axes.labelweight": "semibold",
})

results = {t: {} for t in ("sentiment", "issue_type")}
for target in ("sentiment", "issue_type"):
    y_tr = train[target].astype(str); keep = y_tr != "nan"
    X_tr_text = train.loc[keep, "cleaned_text"].astype(str); y_tr = y_tr[keep]
    rare = {c for c, n in Counter(y_tr).items() if n < 2}
    if rare:
        m = ~y_tr.isin(rare); X_tr_text, y_tr = X_tr_text[m], y_tr[m]
    te = test[test[target].notna()]
    y_te = te[target].astype(str); X_te_text = te["cleaned_text"].astype(str)
    vec = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=1,
                          max_features=10000, sublinear_tf=True)
    X_tr = vec.fit_transform(X_tr_text); X_te = vec.transform(X_te_text)
    k = max(1, min(5, min(Counter(y_tr).values()) - 1))
    X_sm, y_sm = SMOTE(random_state=42, k_neighbors=k).fit_resample(X_tr, y_tr)

    print(f"\n=== {target}  (train={len(y_tr)} -> SMOTE {X_sm.shape[0]}, test={len(y_te)}) ===")
    print(f"{'Model':<22}{'Accuracy':<12}{'Macro-F1':<10}")
    for name, make in MODELS.items():
        clf = make(); clf.fit(X_sm, y_sm); pred = clf.predict(X_te)
        acc = accuracy_score(y_te, pred); f1 = f1_score(y_te, pred, average="macro", zero_division=0)
        results[target][name] = (acc, f1)
        print(f"{name:<22}{acc*100:>6.1f}%     {f1:>6.3f}")

names = list(MODELS)
x = np.arange(2); w = 0.2
fig, ax = plt.subplots(figsize=(8.6, 4.8))
for i, name in enumerate(names):
    vals = [results["sentiment"][name][1], results["issue_type"][name][1]]
    bars = ax.bar(x + (i - 1.5) * w, vals, w, label=name, color=BARCOLORS[i],
                  edgecolor="white", linewidth=0.7)
    for b in bars:
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + 0.012,
                f"{b.get_height():.3f}", ha="center", fontsize=8.5, fontweight="bold")
ax.set_xticks(x); ax.set_xticklabels(["Sentiment", "Issue Type"], fontsize=12)
ax.set_ylim(0, max(0.78, ax.get_ylim()[1]))
ax.set_ylabel("Macro-F1 (held-out test)")
ax.set_title("Model Comparison — Macro-F1 by Classifier  (same features, n=102)", pad=12)
ax.legend(frameon=False, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.12), fontsize=10.5)
ax.spines[["top", "right"]].set_visible(False)
ax.yaxis.grid(True, color=GRID, linewidth=1); ax.set_axisbelow(True)
fig.tight_layout()
fig.savefig(OUT / "model_comparison.png", dpi=220, bbox_inches="tight")
plt.close(fig)
print(f"\nwrote {OUT / 'model_comparison.png'}")
