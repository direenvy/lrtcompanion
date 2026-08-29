"""
Presentation-ready model visualisations for the deployed NLP models.

Loads the SHIPPED sentiment & issue_type pipelines, evaluates them on the
held-out test set, and writes five vivid, poster/slide-friendly figures.
Read-only: never retrains or overwrites a model.

Figures -> D:/FYP-materials/figure-scripts/
  confusion_matrix_sentiment.png
  confusion_matrix_issue_type.png
  per_class_f1.png
  smote_class_balance.png
  ablation_baseline_vs_smote.png

Usage:  python scripts/model_visualizations.py
"""
import sys
from pathlib import Path
from collections import Counter

import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from sklearn.metrics import (confusion_matrix, precision_recall_fscore_support,
                             accuracy_score)
from imblearn.over_sampling import SMOTE
from sklearn.feature_extraction.text import TfidfVectorizer

sys.stdout.reconfigure(encoding="utf-8")

ROOT   = Path("D:/FYP")
OUT    = Path("D:/FYP-materials/figure-scripts")
OUT.mkdir(parents=True, exist_ok=True)
MODELS = ROOT / "backend" / "models"

# ── Vivid, presentation-friendly palette ─────────────────────────────────────
BLUE, RED, GREEN, ORANGE, PURPLE = "#2E86DE", "#EE5253", "#10AC84", "#F79F1F", "#5F27CD"
CORAL, TEAL, MUTED = "#FF6B6B", "#1DD3B0", "#9AA5B1"
INK, GRID = "#1A202C", "#E2E8F0"
# a punchy blue->teal->lime sequential map for the confusion matrices
CMAP = LinearSegmentedColormap.from_list("brand", ["#EAF3FF", "#2E86DE", "#0B3C7A"])

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 12,
    "axes.edgecolor": "#CBD5E0", "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": INK, "ytick.color": INK, "figure.facecolor": "white",
    "axes.facecolor": "white", "savefig.facecolor": "white",
    "axes.titleweight": "bold", "axes.titlesize": 14, "axes.labelweight": "semibold",
})

train = pd.read_csv(ROOT / "data/nlp/final/train_augmented.csv")
test  = pd.read_csv(ROOT / "data/nlp/final/test_labeled.csv")
sent_model  = joblib.load(MODELS / "sentiment_baseline.joblib")
issue_model = joblib.load(MODELS / "issue_type_baseline.joblib")


# ── 1 & 2. Confusion matrices ────────────────────────────────────────────────
def confusion_fig(col, title, model, fname):
    te = test[test[col].notna()]
    y_true = te[col].astype(str)
    y_pred = model.predict(te["cleaned_text"].astype(str))
    labels = sorted(set(y_true) | set(y_pred))
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    acc = accuracy_score(y_true, y_pred)

    fig, ax = plt.subplots(figsize=(1.15 * len(labels) + 2.4, 1.15 * len(labels) + 2))
    im = ax.imshow(cm, cmap=CMAP, vmin=0)
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, rotation=40, ha="right", fontsize=11)
    ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels, fontsize=11)
    ax.set_xlabel("Predicted"); ax.set_ylabel("Actual")
    ax.set_title(f"{title} Classifier — Confusion Matrix\n(n={len(te)},  accuracy {acc*100:.1f}%)", pad=14)
    thresh = cm.max() * 0.55 if cm.max() else 0.5
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, cm[i, j], ha="center", va="center", fontsize=12, fontweight="bold",
                    color="white" if cm[i, j] > thresh else INK)
    ax.set_xticks(np.arange(-.5, len(labels), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(labels), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    for s in ax.spines.values(): s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.outline.set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / fname, dpi=220, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {fname}")


confusion_fig("sentiment",  "Sentiment",  sent_model,  "confusion_matrix_sentiment.png")
confusion_fig("issue_type", "Issue Type", issue_model, "confusion_matrix_issue_type.png")


# ── 3. Per-class precision / recall / F1 (issue-type) ────────────────────────
def per_class_fig():
    te = test[test["issue_type"].notna()]
    y_true = te["issue_type"].astype(str)
    y_pred = issue_model.predict(te["cleaned_text"].astype(str))
    labels = sorted(set(y_true) | set(y_pred))
    p, r, f, sup = precision_recall_fscore_support(y_true, y_pred, labels=labels, zero_division=0)

    x = np.arange(len(labels)); w = 0.26
    fig, ax = plt.subplots(figsize=(max(8, 1.05 * len(labels) + 3), 4.6))
    for offs, vals, c, lab in [(-w, p, BLUE, "Precision"), (0, r, ORANGE, "Recall"), (w, f, GREEN, "F1")]:
        bars = ax.bar(x + offs, vals, w, label=lab, color=c, edgecolor="white", linewidth=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{l}\n(n={s})" for l, s in zip(labels, sup)], fontsize=10)
    ax.set_ylim(0, 1.08); ax.set_ylabel("Score")
    ax.set_title("Issue-Type Classifier — Per-Class Precision / Recall / F1", pad=12)
    ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.16), fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.grid(True, color=GRID, linewidth=1); ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT / "per_class_f1.png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    print("  wrote per_class_f1.png")


per_class_fig()


# ── 4. Class balance before / after SMOTE (issue-type) ───────────────────────
def smote_balance_fig():
    y = train["issue_type"].astype(str); y = y[y != "nan"]
    counts = Counter(y); labels = sorted(counts)
    before = [counts[l] for l in labels]
    vec = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), min_df=1,
                          max_features=10000, sublinear_tf=True)
    X = vec.fit_transform(train.loc[y.index, "cleaned_text"].astype(str))
    k = max(1, min(5, min(counts.values()) - 1))
    _, y_sm = SMOTE(random_state=42, k_neighbors=k).fit_resample(X, y)
    after = [Counter(y_sm)[l] for l in labels]

    x = np.arange(len(labels)); w = 0.4
    fig, ax = plt.subplots(figsize=(max(8, 1.05 * len(labels) + 3), 4.6))
    ax.bar(x - w/2, before, w, label="Before SMOTE", color=CORAL, edgecolor="white", linewidth=0.6)
    ax.bar(x + w/2, after,  w, label="After SMOTE",  color=TEAL,  edgecolor="white", linewidth=0.6)
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=11)
    ax.set_ylabel("Training samples")
    ax.set_title("Issue-Type Training Distribution — Before vs After SMOTE", pad=12)
    ax.legend(frameon=False, fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.grid(True, color=GRID, linewidth=1); ax.set_axisbelow(True)
    for i, v in enumerate(before):
        ax.text(i - w/2, v + 3, str(v), ha="center", fontsize=9, color=INK)
    fig.tight_layout()
    fig.savefig(OUT / "smote_class_balance.png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    print("  wrote smote_class_balance.png")


smote_balance_fig()


# ── 5. Ablation: baseline vs SMOTE ───────────────────────────────────────────
def ablation_fig():
    data = {  # reproduced from train_with_smote.py, current 573/102 split
        "Sentiment\nAccuracy":  (0.853, 0.853),
        "Sentiment\nMacro-F1":  (0.498, 0.498),
        "Issue-Type\nAccuracy": (0.578, 0.627),
        "Issue-Type\nMacro-F1": (0.567, 0.650),
    }
    labels = list(data)
    base  = [data[l][0] for l in labels]
    smote = [data[l][1] for l in labels]
    x = np.arange(len(labels)); w = 0.38
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    b1 = ax.bar(x - w/2, base,  w, label="Baseline",   color=MUTED, edgecolor="white", linewidth=0.6)
    b2 = ax.bar(x + w/2, smote, w, label="With SMOTE", color=BLUE,  edgecolor="white", linewidth=0.6)
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=10.5)
    ax.set_ylim(0, 1.0); ax.set_ylabel("Score")
    ax.set_title("Model Ablation — Baseline vs SMOTE  (held-out test, n=102)", pad=12)
    ax.legend(frameon=False, fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.grid(True, color=GRID, linewidth=1); ax.set_axisbelow(True)
    for bars in (b1, b2):
        for bar in bars:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.015,
                    f"{bar.get_height():.3f}", ha="center", fontsize=9, fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUT / "ablation_baseline_vs_smote.png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    print("  wrote ablation_baseline_vs_smote.png")


ablation_fig()
print(f"\nAll figures written to {OUT}")
