"""
Upload the RAG embedding cache into the Supabase pgvector table `rag_chunks`.

pgvector is the canonical persistent vector store (per the project objective);
the backend keeps `rag_embeddings_cache.pkl` as a local performance cache so
retrieval is zero-latency and the test suite stays offline.

Usage (after any corpus re-embed):
    cd D:/FYP
    python scripts/upload_embeddings_pgvector.py
"""
import pickle
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from db.supabase_client import _get_client  # loads backend/.env

CACHE = Path(__file__).resolve().parent.parent / "backend" / "models" / "rag_embeddings_cache.pkl"
BATCH = 25


def main() -> None:
    sb = _get_client()
    if sb is None:
        print("Supabase client not available — check backend/.env")
        sys.exit(1)

    with CACHE.open("rb") as f:
        cache = pickle.load(f)
    chunks, embeddings = cache["chunks"], cache["embeddings"]
    print(f"Cache: {len(chunks)} chunks, model {cache.get('model')}, "
          f"dim {len(embeddings[0])}")
    assert len(chunks) == len(embeddings)

    rows = []
    for c, e in zip(chunks, embeddings):
        rows.append({
            "chunk_id":      c["chunk_id"],
            "source_file":   c.get("source_file", ""),
            "document_type": c.get("document_type", ""),
            "chunk_index":   c.get("chunk_index", 0),
            "content":       c["text"],
            # pgvector accepts the '[x,y,...]' literal through PostgREST
            "embedding":     "[" + ",".join(f"{v:.7f}" for v in e) + "]",
        })

    for i in range(0, len(rows), BATCH):
        sb.table("rag_chunks").upsert(rows[i:i + BATCH]).execute()
        done = min(i + BATCH, len(rows))
        if done % 250 < BATCH or done == len(rows):
            print(f"  upserted {done}/{len(rows)}")

    count = sb.table("rag_chunks").select("chunk_id", count="exact").execute().count
    print(f"Done. rag_chunks now holds {count} rows.")


if __name__ == "__main__":
    main()
