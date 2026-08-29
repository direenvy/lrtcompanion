import argparse
import csv
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
NLP_INTERIM_DIR = DATA_DIR / "nlp" / "interim"

DEFAULT_INPUT = NLP_INTERIM_DIR / "labeling_sample_300.csv"
DEFAULT_OUTPUT = NLP_INTERIM_DIR / "labeling_sample_300_prelabeled.csv"

RELEVANT_PATTERNS = [
    r"\baskrapidkl\b",
    r"\brapidkl\b",
    r"\brapid kl\b",
    r"\bprasarana\b",
    r"\bmyrapid\b",
    r"\blrt\b",
    r"\bmrt\b",
    r"\bmonorail\b",
    r"\brapid bus\b",
    r"\bkelana jaya\b",
    r"\bsri petaling\b",
    r"\bampang\b",
    r"\bkajang\b",
    r"\bputrajaya\b",
    r"\bputra heights\b",
    r"\bstation\b",
    r"\bcoach\b",
]

IRRELEVANT_PATTERNS = [
    r"\bskytrain\b",
    r"\blangley\b",
    r"\bmaple ridge\b",
    r"\bopen is getting the pulse\b",
    r"\bstocks?\b",
    r"\bai prediction\b",
    r"\blelang\b",
    r"\bkarhutla\b",
    r"\bkejati\b",
    r"\byonif\b",
    r"\bcenderawasih\b",
    r"\butilitas\b",
]

ISSUE_RULES = [
    ("breakdown", [r"\brosak\b", r"technical", r"out of service", r"problem", r"issue"]),
    ("delay", [r"\bslow\b", r"\blambat\b", r"\binterval\b", r"\bwait\b", r"\bstuck\b", r"\bdelay\b"]),
    ("crowding", [r"\bcrowded\b", r"\bsesak\b", r"\bpacked\b", r"\bpeak hour\b"]),
    ("aircond", [r"\baircond\b", r"\bpanas\b", r"\bhot\b", r"\bbau\b"]),
    ("app_issue", [r"\bapp\b", r"\bpulse\b", r"\btracking\b", r"\blogin\b"]),
    ("cleanliness", [r"\bdirty\b", r"\bkotor\b", r"\bclean\b"]),
    ("staff_service", [r"\bstaff\b", r"\bdriver\b", r"\bmanagement\b", r"\bservice\b"]),
    ("fare_ticket", [r"\btoken\b", r"\bticket\b", r"\bfare\b", r"\brefund\b", r"\bpass\b"]),
    ("information", [r"\bwhy\b", r"\bwhat happened\b", r"\bupdate\b", r"\bhelp\b", r"\bplease\b"]),
]

ROUTE_RULES = [
    ("kelana_jaya", [r"\bkelana jaya\b", r"\bgombak\b", r"\bputra heights\b"]),
    ("ampang", [r"\bampang\b"]),
    ("sri_petaling", [r"\bsri petaling\b"]),
    ("kajang", [r"\bkajang\b"]),
    ("putrajaya", [r"\bputrajaya\b"]),
    ("monorail", [r"\bmonorail\b"]),
    ("rapid_bus", [r"\brapid bus\b", r"\bfeeder bus\b", r"\bbus\b"]),
]

POSITIVE_PATTERNS = [r"\bthank you\b", r"\bgood\b", r"\bbest\b", r"\bhelpful\b", r"\bappreciate\b"]
NEGATIVE_PATTERNS = [
    r"\brosak\b",
    r"\bslow\b",
    r"\blambat\b",
    r"\bstuck\b",
    r"\bannoying\b",
    r"\bwtf\b",
    r"\bpanas\b",
    r"\bsesak\b",
    r"\bfucked up\b",
    r"\bcrap\b",
    r"\bproblem\b",
    r"\bbau\b",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pre-label transport tweet samples using rules.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Input CSV to pre-label.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output CSV with predictions.")
    return parser.parse_args()


def matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def first_match_label(text: str, rules: list[tuple[str, list[str]]], default_value: str) -> str:
    for label, patterns in rules:
        if matches_any(text, patterns):
            return label
    return default_value


def predict_relevance(text: str) -> str:
    if matches_any(text, IRRELEVANT_PATTERNS):
        return "not_relevant"
    if matches_any(text, RELEVANT_PATTERNS):
        return "relevant"
    return "not_relevant"


def predict_sentiment(text: str, relevance: str) -> str:
    if relevance != "relevant":
        return ""
    if matches_any(text, NEGATIVE_PATTERNS):
        return "negative"
    if matches_any(text, POSITIVE_PATTERNS):
        return "positive"
    return "neutral"


def predict_issue_type(text: str, relevance: str) -> str:
    if relevance != "relevant":
        return ""
    return first_match_label(text, ISSUE_RULES, "other")


def predict_route_line(text: str, relevance: str) -> str:
    if relevance != "relevant":
        return ""
    return first_match_label(text, ROUTE_RULES, "unknown")


def read_rows(input_path: Path) -> list[dict]:
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(output_path: Path, rows: list[dict]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    rows = read_rows(Path(args.input))

    for row in rows:
        text = row.get("cleaned_text", "").strip()
        predicted_relevance = predict_relevance(text)
        predicted_sentiment = predict_sentiment(text, predicted_relevance)
        predicted_issue_type = predict_issue_type(text, predicted_relevance)
        predicted_route_line = predict_route_line(text, predicted_relevance)

        row["relevance"] = predicted_relevance
        row["sentiment"] = predicted_sentiment
        row["issue_type"] = predicted_issue_type
        row["route_line"] = predicted_route_line
        row["notes"] = "review_needed"

    write_rows(Path(args.output), rows)

    relevant_count = sum(1 for row in rows if row.get("relevance") == "relevant")
    print(f"Input rows: {len(rows)}")
    print(f"Predicted relevant rows: {relevant_count}")
    print(f"Output file: {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
