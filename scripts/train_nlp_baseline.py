import argparse
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.pipeline import Pipeline


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
NLP_FINAL_DIR = DATA_DIR / "nlp" / "final"
NLP_OUTPUTS_DIR = DATA_DIR / "nlp" / "outputs"

DEFAULT_TRAIN = NLP_FINAL_DIR / "train_labeled.csv"
DEFAULT_TEST = NLP_FINAL_DIR / "test_labeled.csv"
DEFAULT_TEXT_COLUMN = "cleaned_text"
VALID_TARGETS = {"sentiment", "issue_type"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train and evaluate a simple NLP baseline for the labeled transport dataset."
    )
    parser.add_argument(
        "--train",
        default=str(DEFAULT_TRAIN),
        help="Path to the training CSV.",
    )
    parser.add_argument(
        "--test",
        default=str(DEFAULT_TEST),
        help="Path to the test CSV.",
    )
    parser.add_argument(
        "--target",
        choices=sorted(VALID_TARGETS),
        default="sentiment",
        help="Label column to predict.",
    )
    parser.add_argument(
        "--text-column",
        default=DEFAULT_TEXT_COLUMN,
        help="Text column to use as model input.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(NLP_OUTPUTS_DIR),
        help="Directory to store metrics, predictions, and model files.",
    )
    return parser.parse_args()


def load_dataset(path: Path, text_column: str, target: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    required_columns = {text_column, target}
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in {path.name}: {sorted(missing)}")

    df = df[df[text_column].notna() & df[target].notna()].copy()
    df[text_column] = df[text_column].astype(str).str.strip()
    df[target] = df[target].astype(str).str.strip()
    df = df[(df[text_column] != "") & (df[target] != "")]
    return df


def build_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    ngram_range=(1, 2),
                    min_df=1,
                    max_features=5000,
                    sublinear_tf=True,
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=42,
                ),
            ),
        ]
    )


def save_outputs(
    output_dir: Path,
    target: str,
    model: Pipeline,
    metrics: dict,
    predictions_df: pd.DataFrame,
) -> None:
    target_dir = output_dir / target
    target_dir.mkdir(parents=True, exist_ok=True)

    model_path = target_dir / f"{target}_baseline.joblib"
    metrics_path = target_dir / f"{target}_metrics.json"
    report_path = target_dir / f"{target}_classification_report.txt"
    predictions_path = target_dir / f"{target}_predictions.csv"

    joblib.dump(model, model_path)

    with metrics_path.open("w", encoding="utf-8") as handle:
        json.dump(metrics, handle, indent=2)

    with report_path.open("w", encoding="utf-8") as handle:
        handle.write(metrics["classification_report"])

    predictions_df.to_csv(predictions_path, index=False, encoding="utf-8-sig")


def main() -> None:
    args = parse_args()
    train_path = Path(args.train)
    test_path = Path(args.test)
    output_dir = Path(args.output_dir)

    train_df = load_dataset(train_path, args.text_column, args.target)
    test_df = load_dataset(test_path, args.text_column, args.target)

    model = build_pipeline()
    model.fit(train_df[args.text_column], train_df[args.target])

    predictions = model.predict(test_df[args.text_column])
    labels = sorted(set(train_df[args.target]) | set(test_df[args.target]))

    report_text = classification_report(
        test_df[args.target],
        predictions,
        labels=labels,
        zero_division=0,
    )
    accuracy = accuracy_score(test_df[args.target], predictions)
    matrix = confusion_matrix(test_df[args.target], predictions, labels=labels)

    metrics = {
        "target": args.target,
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "labels": labels,
        "accuracy": accuracy,
        "confusion_matrix": matrix.tolist(),
        "classification_report": report_text,
    }

    predictions_df = test_df.copy()
    predictions_df["predicted_label"] = predictions
    predictions_df["is_correct"] = predictions_df[args.target] == predictions_df["predicted_label"]

    save_outputs(output_dir, args.target, model, metrics, predictions_df)

    print(f"Target: {args.target}")
    print(f"Train rows: {len(train_df)}")
    print(f"Test rows: {len(test_df)}")
    print(f"Accuracy: {accuracy:.4f}")
    print("Classification report:")
    print(report_text)
    print(f"Saved outputs under: {(output_dir / args.target).resolve()}")


if __name__ == "__main__":
    main()
