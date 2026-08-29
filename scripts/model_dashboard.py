"""
Combined NLP evaluation dashboard — ONE poster/slide-ready figure.

Panels (the three that actually show a difference):
  (a) Issue-type class balance, before vs after SMOTE      [full width, top]
  (b) Ablation: baseline vs SMOTE                          [bottom-left]
  (c) Model comparison: LR vs SVM vs NB vs RF (macro-F1)   [bottom-right]

Read-only. Output -> D:/FYP-materials/figure-scripts/model_evaluation_dashboard.png
Usage:  python scripts/model_dashboard.py
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

BLUE, RED, GREEN, ORANGE, PURPLE = "#2E86DE", "#EE5253", "#10AC84", "#F79F1F", "#5F27CD"
CORAL, TEAL, MUTED = "#FF6B6B", "#1DD3B0", "#9AA5B1"
INK, GRID = "#1A202C", "#E2E8F0"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 12, "text.color": INK,
    "axes.edgecolor": "#CBD5E0", "xtick.color": INK, "ytick.color": INK,
    "axes.facecolor": "white", "figure.facecolor": "white", "savefig.facecolor": "white",
    "axes.titleweight": "bold", "axes.labelweight": "semibold",
})

train = pd.read_csv(ROOT / "data/nlp/final/train_augmented.csv")
test  = pd.read_csv(ROOT / "data/nlp/final/test_labeled.csv")


def issue_train_xy():
    y = train["issue_type"].astype(str); y = y[y != "nan"]
    X = train.loc[y.index, "cleaned_text"].astype(str)
    rare = {c for c, n in Counter(y).items() if n < 2}
    if rare:
        m = ~y.isin(rare); X, y = X[m], y[m]
    return X, y


# ── figure + layout ──────────────────────────────────────────────────────────
fig = plt.figure(figsize=(14, 8.6))
gs = fig.add_gridspec(2, 2, height_ratios=[1, 1], hspace=0.55, wspace=0.22,
                      left=0.07, right=0.98, top=0.88, bottom=0.13)
ax_a = fig.add_subplot(gs[0, :])
ax_b = fig.add_subplot(gs[1, 0])
ax_c = fig.add_subplot(gs[1, 1])
fig.suptitle("NLP Model Evaluation  —  LRT Companion", fontsize=19, fontweight="bold", y=0.955)


# ── (a) SMOTE class balance ──────────────────────────────────────────────────
Xtxt, y = issue_train_xy()
counts = Counter(y); labels = sorted(counts)
before = [counts[l] for l in labels]
vec = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=1, max_features=10000, sublinear_tf=True)
Xv = vec.fit_transform(Xtxt)
k = max(1, min(5, min(counts.values()) - 1))
_, y_sm = SMOTE(random_state=42, k_neighbors=k).fit_resample(Xv, y)
after = [Counter(y_sm)[l] for l in labels]
x = np.arange(len(labels)); w = 0.4
ax_a.bar(x - w/2, before, w, label="Before SMOTE", color=CORAL, edgecolor="white", linewidth=0.6)
ax_a.bar(x + w/2, after,  w, label="After SMOTE",  color=TEAL,  edgecolor="white", linewidth=0.6)
ax_a.set_xticks(x); ax_a.set_xticklabels(labels, rotation=18, ha="right", fontsize=11)
ax_a.set_ylabel("Training samples")
ax_a.set_title("(a)  Issue-Type Class Balance — Before vs After SMOTE", fontsize=13, pad=8, loc="left")
ax_a.legend(frameon=False, fontsize=11, loc="upper right")
ax_a.spines[["top", "right"]].set_visible(False)
ax_a.yaxis.grid(True, color=GRID); ax_a.set_axisbelow(True)


# ── (b) ablation ─────────────────────────────────────────────────────────────
adata = {"Sentiment\nAcc": (0.853, 0.853), "Sentiment\nMacro-F1": (0.498, 0.498),
         "Issue\nAcc": (0.578, 0.627), "Issue\nMacro-F1": (0.567, 0.650)}
al = list(adata); base = [adata[l][0] for l in al]; sm = [adata[l][1] for l in al]
x = np.arange(len(al)); w = 0.38
b1 = ax_b.bar(x - w/2, base, w, label="Baseline", color=MUTED, edgecolor="white", linewidth=0.6)
b2 = ax_b.bar(x + w/2, sm,   w, label="With SMOTE", color=BLUE, edgecolor="white", linewidth=0.6)
ax_b.set_xticks(x); ax_b.set_xticklabels(al, fontsize=9.5)
ax_b.set_ylim(0, 1.0); ax_b.set_ylabel("Score")
ax_b.set_title("(b)  Ablation — Baseline vs SMOTE", fontsize=13, pad=8, loc="left")
ax_b.legend(frameon=False, fontsize=10)
ax_b.spines[["top", "right"]].set_visible(False)
ax_b.yaxis.grid(True, color=GRID); ax_b.set_axisbelow(True)
for bars in (b1, b2):
    for bar in bars:
        ax_b.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.015,
                  f"{bar.get_height():.2f}", ha="center", fontsize=8, fontweight="bold")


# ── (c) model comparison ─────────────────────────────────────────────────────
MODELS = {
    "Logistic Regression": lambda: LogisticRegression(max_iter=2000, C=1.0, random_state=42),
    "Linear SVM":          lambda: LinearSVC(C=1.0, random_state=42),
    "Naive Bayes":         lambda: MultinomialNB(),
    "Random Forest":       lambda: RandomForestClassifier(n_estimators=300, random_state=42),
}
BARC = [BLUE, RED, GREEN, ORANGE]
res = {t: {} for t in ("sentiment", "issue_type")}
for target in ("sentiment", "issue_type"):
    yt = train[target].astype(str); keep = yt != "nan"
    Xt = train.loc[keep, "cleaned_text"].astype(str); yt = yt[keep]
    rare = {c for c, n in Counter(yt).items() if n < 2}
    if rare:
        m = ~yt.isin(rare); Xt, yt = Xt[m], yt[m]
    te = test[test[target].notna()]; yte = te[target].astype(str)
    v = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=1, max_features=10000, sublinear_tf=True)
    Xtr = v.fit_transform(Xt); Xte = v.transform(te["cleaned_text"].astype(str))
    kk = max(1, min(5, min(Counter(yt).values()) - 1))
    Xs, ys = SMOTE(random_state=42, k_neighbors=kk).fit_resample(Xtr, yt)
    for name, make in MODELS.items():
        clf = make(); clf.fit(Xs, ys)
        res[target][name] = f1_score(yte, clf.predict(Xte), average="macro", zero_division=0)
x = np.arange(2); w = 0.2
for i, name in enumerate(MODELS):
    vals = [res["sentiment"][name], res["issue_type"][name]]
    bars = ax_c.bar(x + (i - 1.5) * w, vals, w, label=name, color=BARC[i], edgecolor="white", linewidth=0.7)
    for b in bars:
        ax_c.text(b.get_x()+b.get_width()/2, b.get_height()+0.012, f"{b.get_height():.2f}",
                  ha="center", fontsize=7.5, fontweight="bold")
ax_c.set_xticks(x); ax_c.set_xticklabels(["Sentiment", "Issue Type"], fontsize=11)
ax_c.set_ylim(0, 0.8); ax_c.set_ylabel("Macro-F1")
ax_c.set_title("(c)  Model Comparison — Macro-F1", fontsize=13, pad=8, loc="left")
ax_c.legend(frameon=False, ncol=2, fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.14))
ax_c.spines[["top", "right"]].set_visible(False)
ax_c.yaxis.grid(True, color=GRID); ax_c.set_axisbelow(True)

fig.savefig(OUT / "model_evaluation_dashboard.png", dpi=220, bbox_inches="tight")
plt.close(fig)
print(f"wrote {OUT / 'model_evaluation_dashboard.png'}")
