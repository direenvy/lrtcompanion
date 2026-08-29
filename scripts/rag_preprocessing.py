import argparse
import csv
import json
import logging
import os
from collections import Counter
from pathlib import Path

from PyPDF2 import PdfReader

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAG_DIR = DATA_DIR / "rag"

DEFAULT_KB_DIR = RAG_DIR / "knowledge_base"
DEFAULT_MANIFEST = RAG_DIR / "outputs" / "document_manifest.csv"
DEFAULT_CHUNKS = RAG_DIR / "outputs" / "chunked_documents.jsonl"
DEFAULT_COLLECTION = "prasarana_knowledge_base"

SUPPORTED_EXTENSIONS = {".pdf", ".txt"}

# PyPDF2 can emit very noisy font-width warnings for some PDFs even when
# text extraction succeeds. Keep the console output focused on our pipeline.
logging.getLogger("PyPDF2").setLevel(logging.ERROR)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan, extract, chunk, and optionally vectorize the RAG knowledge base."
    )
    parser.add_argument(
        "--kb-dir",
        default=str(DEFAULT_KB_DIR),
        help="Path to the RAG knowledge base folder.",
    )
    parser.add_argument(
        "--manifest-out",
        default=str(DEFAULT_MANIFEST),
        help="Path to write the document manifest CSV.",
    )
    parser.add_argument(
        "--chunks-out",
        default=str(DEFAULT_CHUNKS),
        help="Path to write extracted/chunked documents as JSONL.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1000,
        help="Characters per chunk.",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=200,
        help="Character overlap between chunks.",
    )
    parser.add_argument(
        "--store-vectors",
        action="store_true",
        help="Store chunks into PGVector using Gemini embeddings.",
    )
    parser.add_argument(
        "--collection-name",
        default=DEFAULT_COLLECTION,
        help="PGVector collection name when --store-vectors is used.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan files and write manifest only, without extraction/chunking.",
    )
    return parser.parse_args()


def categorize_document(path: Path, kb_dir: Path) -> str:
    try:
        relative_parts = path.relative_to(kb_dir).parts
    except ValueError:
        return "unknown"
    return relative_parts[0] if relative_parts else "unknown"


def scan_documents(kb_dir: Path) -> tuple[list[Path], list[Path]]:
    supported = []
    skipped = []
    for path in sorted(kb_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            supported.append(path)
        else:
            skipped.append(path)
    return supported, skipped


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages).strip()


def extract_txt_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_text(path)
    if suffix == ".txt":
        return extract_txt_text(path)
    raise ValueError(f"Unsupported file type: {path}")


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if not text:
        return []

    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunks.append(text[start:end].strip())
        if end == text_length:
            break
        start = max(end - chunk_overlap, start + 1)

    return [chunk for chunk in chunks if chunk]


def build_manifest_rows(
    kb_dir: Path,
    supported: list[Path],
    skipped: list[Path],
) -> list[dict]:
    rows = []
    for path in supported:
        rows.append(
            {
                "filename": path.name,
                "relative_path": str(path.relative_to(kb_dir)),
                "document_type": categorize_document(path, kb_dir),
                "extension": path.suffix.lower(),
                "size_bytes": path.stat().st_size,
                "status": "supported",
                "source_url": "",
                "notes": "",
            }
        )

    for path in skipped:
        rows.append(
            {
                "filename": path.name,
                "relative_path": str(path.relative_to(kb_dir)),
                "document_type": categorize_document(path, kb_dir),
                "extension": path.suffix.lower(),
                "size_bytes": path.stat().st_size,
                "status": "skipped",
                "source_url": "",
                "notes": "unsupported file type",
            }
        )

    return rows


def write_manifest(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_chunk_rows(
    kb_dir: Path,
    supported: list[Path],
    chunk_size: int,
    chunk_overlap: int,
) -> tuple[list[dict], list[dict]]:
    chunk_rows = []
    extraction_summary = []

    for path in supported:
        document_type = categorize_document(path, kb_dir)
        try:
            text = extract_text(path)
            chunks = chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            extraction_summary.append(
                {
                    "relative_path": str(path.relative_to(kb_dir)),
                    "document_type": document_type,
                    "characters": len(text),
                    "chunks": len(chunks),
                    "status": "ok",
                }
            )

            for index, chunk in enumerate(chunks, start=1):
                chunk_rows.append(
                    {
                        "source_file": path.name,
                        "relative_path": str(path.relative_to(kb_dir)),
                        "document_type": document_type,
                        "chunk_id": f"{path.stem}_{index:04d}",
                        "chunk_index": index,
                        "text": chunk,
                    }
                )
        except Exception as exc:
            extraction_summary.append(
                {
                    "relative_path": str(path.relative_to(kb_dir)),
                    "document_type": document_type,
                    "characters": 0,
                    "chunks": 0,
                    "status": f"error: {type(exc).__name__}: {exc}",
                }
            )

    return chunk_rows, extraction_summary


def write_chunks_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def store_vectors(chunk_rows: list[dict], collection_name: str) -> None:
    try:
        from langchain.schema import Document
        from langchain.text_splitter import RecursiveCharacterTextSplitter
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        from langchain_postgres.vectorstores import PGVector
    except Exception as exc:
        raise RuntimeError(
            "Vector storage dependencies are missing. Install langchain, "
            "langchain-google-genai, and langchain-postgres first."
        ) from exc

    api_key = os.getenv("GOOGLE_API_KEY")
    connection_string = os.getenv("PGVECTOR_CONNECTION_STRING")
    if not api_key:
        raise RuntimeError("Set GOOGLE_API_KEY before using --store-vectors.")
    if not connection_string:
        raise RuntimeError("Set PGVECTOR_CONNECTION_STRING before using --store-vectors.")

    # Re-split with LangChain's splitter for consistency if vector storage is requested.
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
    )

    docs = []
    for row in chunk_rows:
        docs.append(
            Document(
                page_content=row["text"],
                metadata={
                    "source_file": row["source_file"],
                    "relative_path": row["relative_path"],
                    "document_type": row["document_type"],
                    "chunk_id": row["chunk_id"],
                },
            )
        )

    docs = text_splitter.split_documents(docs)
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")

    PGVector.from_documents(
        embedding=embeddings,
        documents=docs,
        collection_name=collection_name,
        connection=connection_string,
        use_jsonb=True,
    )


def print_summary(
    supported: list[Path],
    skipped: list[Path],
    extraction_summary: list[dict],
    chunk_rows: list[dict],
) -> None:
    supported_counter = Counter(path.suffix.lower() for path in supported)
    type_counter = Counter(
        row["document_type"] for row in extraction_summary if row["status"] == "ok"
    )

    print(f"Supported documents found: {len(supported)}")
    print(f"Skipped files: {len(skipped)}")
    print(f"Generated chunks: {len(chunk_rows)}")
    print(f"Supported by extension: {dict(supported_counter)}")
    print(f"Extracted by document type: {dict(type_counter)}")

    if skipped:
        print("Skipped files:")
        for path in skipped:
            print(f"  - {path}")

    failed = [row for row in extraction_summary if row["status"] != "ok"]
    if failed:
        print("Extraction issues:")
        for row in failed:
            print(f"  - {row['relative_path']}: {row['status']}")


def main() -> None:
    args = parse_args()
    kb_dir = Path(args.kb_dir)
    manifest_out = Path(args.manifest_out)
    chunks_out = Path(args.chunks_out)

    if not kb_dir.exists():
        raise FileNotFoundError(f"Knowledge base folder not found: {kb_dir}")

    supported, skipped = scan_documents(kb_dir)
    manifest_rows = build_manifest_rows(kb_dir, supported, skipped)
    if manifest_rows:
        write_manifest(manifest_out, manifest_rows)

    if args.dry_run:
        print_summary(supported, skipped, [], [])
        print(f"Manifest written to: {manifest_out.resolve()}")
        return

    chunk_rows, extraction_summary = build_chunk_rows(
        kb_dir=kb_dir,
        supported=supported,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )

    if chunk_rows:
        write_chunks_jsonl(chunks_out, chunk_rows)

    if args.store_vectors:
        store_vectors(chunk_rows, collection_name=args.collection_name)
        print("Vector storage completed.")

    print_summary(supported, skipped, extraction_summary, chunk_rows)
    print(f"Manifest written to: {manifest_out.resolve()}")
    print(f"Chunks written to: {chunks_out.resolve()}")


if __name__ == "__main__":
    main()
