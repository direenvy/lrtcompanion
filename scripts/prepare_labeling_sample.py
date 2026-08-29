import argparse
import csv
import random
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
NLP_INTERIM_DIR = DATA_DIR / "nlp" / "interim"

DEFAULT_INPUT = NLP_INTERIM_DIR / "cleaned_x_transport.csv"
DEFAULT_OUTPUT = NLP_INTERIM_DIR / "labeling_sample_300.csv"

LABEL_COLUMNS = [
    "relevance",
    "sentiment",
    "issue_type",
    "route_line",
    "notes",
]

RELEVANCE_GUIDE = "relevant/not_relevant"
SENTIMENT_GUIDE = "positive/neutral/negative"
ISSUE_TYPE_GUIDE = (
    "delay/breakdown/crowding/aircond/app_issue/cleanliness/"
    "staff_service/fare_ticket/information/other"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a manual-labeling sample from cleaned transport tweets."
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT),
        help="Path to the cleaned CSV file.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Path to the labeling sample CSV to create.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=300,
        help="Number of rows to sample.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible sampling.",
    )
    return parser.parse_args()


def read_rows(input_path: Path) -> list[dict]:
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def build_sample(rows: list[dict], sample_size: int, seed: int) -> list[dict]:
    if not rows:
        raise ValueError("The input CSV is empty.")

    sample_size = min(sample_size, len(rows))
    rng = random.Random(seed)
    sampled_rows = rng.sample(rows, sample_size)

    output_rows = []
    for index, row in enumerate(sampled_rows, start=1):
        prepared = dict(row)
        prepared["sample_id"] = f"S{index:03d}"
        prepared["relevance"] = ""
        prepared["sentiment"] = ""
        prepared["issue_type"] = ""
        prepared["route_line"] = ""
        prepared["notes"] = ""
        prepared["label_guide_relevance"] = RELEVANCE_GUIDE
        prepared["label_guide_sentiment"] = SENTIMENT_GUIDE
        prepared["label_guide_issue_type"] = ISSUE_TYPE_GUIDE
        output_rows.append(prepared)

    return output_rows


def write_rows(output_path: Path, rows: list[dict]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["sample_id"] + list(rows[0].keys())
    # Remove duplicate sample_id if it already exists in the row keys.
    fieldnames = list(dict.fromkeys(fieldnames))

    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    rows = read_rows(input_path)
    sampled_rows = build_sample(rows, args.sample_size, args.seed)
    write_rows(output_path, sampled_rows)

    print(f"Input file: {input_path.resolve()}")
    print(f"Output file: {output_path.resolve()}")
    print(f"Available rows: {len(rows)}")
    print(f"Sample size: {len(sampled_rows)}")
    print("Label columns added: " + ", ".join(LABEL_COLUMNS))


if __name__ == "__main__":
    main()
