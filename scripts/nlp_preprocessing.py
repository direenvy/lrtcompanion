import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
NLP_INTERIM_DIR = DATA_DIR / "nlp" / "interim"

DEFAULT_INPUT = (
    r"c:\Users\limho\Downloads"
    r"\dataset_twitter-x-data-tweet-scraper-pay-per-result-cheapest_2026-04-13_15-33-57-418.json"
)
DEFAULT_OUTPUT = NLP_INTERIM_DIR / "cleaned_x_transport.csv"

TRANSPORT_KEYWORDS = [
    "askrapidkl",
    "rapidkl",
    "rapid kl",
    "prasarana",
    "myrapid",
    "pulse app",
    "pulse",
    "lrt",
    "mrt",
    "monorail",
    "rapid bus",
    "feeder bus",
    "kelana jaya",
    "ampang line",
    "ampang",
    "sri petaling",
    "kajang line",
    "putrajaya line",
    "kajang",
    "putrajaya",
    "gombak",
    "putra heights",
]

ALLOWED_LANGS = {"en", "in", "ms", "und"}
URL_PATTERN = re.compile(r"https?://\S+")
WHITESPACE_PATTERN = re.compile(r"\s+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filter and clean X posts related to Rapid KL / Prasarana transport issues."
    )
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        help="Path to the raw JSON export from the X scraper.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Path to the cleaned CSV file to create.",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=12,
        help="Minimum cleaned text length to keep.",
    )
    parser.add_argument(
        "--keep-replies",
        action="store_true",
        help="Keep reply tweets. By default, replies are kept anyway for complaint analysis.",
    )
    return parser.parse_args()


def load_json_records(input_path: Path) -> list[dict]:
    with input_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, list):
        raise ValueError("Expected the JSON file to contain a list of tweet objects.")

    return [record for record in data if isinstance(record, dict)]


def clean_text(text: str) -> str:
    text = text.replace("\r", " ").replace("\n", " ")
    text = URL_PATTERN.sub("", text)
    text = WHITESPACE_PATTERN.sub(" ", text)
    return text.strip()


def get_matched_keywords(text: str) -> list[str]:
    lowered = text.lower()
    return [keyword for keyword in TRANSPORT_KEYWORDS if keyword in lowered]


def normalize_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def should_keep_record(record: dict, min_length: int) -> tuple[bool, list[str], str]:
    raw_text = str(record.get("text", "")).strip()
    if not raw_text:
        return False, [], ""

    cleaned = clean_text(raw_text)
    if len(cleaned) < min_length:
        return False, [], cleaned

    lang = str(record.get("lang", "")).strip().lower()
    if lang and lang not in ALLOWED_LANGS:
        return False, [], cleaned

    matched_keywords = get_matched_keywords(cleaned)
    if not matched_keywords:
        return False, [], cleaned

    return True, matched_keywords, cleaned


def build_output_rows(records: list[dict], min_length: int) -> tuple[list[dict], dict]:
    seen_ids = set()
    output_rows = []
    keyword_counter = Counter()
    stats = {
        "raw_rows": len(records),
        "duplicate_ids_removed": 0,
        "filtered_out": 0,
        "kept_rows": 0,
    }

    for record in records:
        tweet_id = str(record.get("id", "")).strip()
        if tweet_id:
            if tweet_id in seen_ids:
                stats["duplicate_ids_removed"] += 1
                continue
            seen_ids.add(tweet_id)

        keep, matched_keywords, cleaned = should_keep_record(record, min_length)
        if not keep:
            stats["filtered_out"] += 1
            continue

        keyword_counter.update(matched_keywords)
        output_rows.append(
            {
                "id": tweet_id,
                "created_at": record.get("createdAt", ""),
                "lang": record.get("lang", ""),
                "url": record.get("url", ""),
                "raw_text": str(record.get("text", "")).strip(),
                "cleaned_text": cleaned,
                "matched_keywords": ", ".join(matched_keywords),
                "is_reply": normalize_bool(record.get("isReply")),
                "is_retweet": normalize_bool(record.get("isRetweet")),
                "is_quote": normalize_bool(record.get("isQuote")),
                "like_count": record.get("likeCount", 0),
                "reply_count": record.get("replyCount", 0),
                "retweet_count": record.get("retweetCount", 0),
                "quote_count": record.get("quoteCount", 0),
                "view_count": record.get("viewCount", 0),
                "bookmark_count": record.get("bookmarkCount", 0),
                "source_dataset": "x_json_export",
            }
        )

    stats["kept_rows"] = len(output_rows)
    stats["top_keywords"] = keyword_counter.most_common(10)
    return output_rows, stats


def write_csv(output_path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError("No rows matched the filtering rules, so no CSV was created.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())

    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    records = load_json_records(input_path)
    output_rows, stats = build_output_rows(records, min_length=args.min_length)
    write_csv(output_path, output_rows)

    print(f"Input file: {input_path}")
    print(f"Output file: {output_path.resolve()}")
    print(f"Raw rows: {stats['raw_rows']}")
    print(f"Duplicate IDs removed: {stats['duplicate_ids_removed']}")
    print(f"Filtered out: {stats['filtered_out']}")
    print(f"Kept rows: {stats['kept_rows']}")

    if stats["top_keywords"]:
        print("Top matched keywords:")
        for keyword, count in stats["top_keywords"]:
            print(f"  - {keyword}: {count}")


if __name__ == "__main__":
    main()
