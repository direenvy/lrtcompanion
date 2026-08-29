"""
RAG Chatbot Agent
- If embedding cache exists: full semantic search via cosine similarity
- If cache not ready yet: keyword-based fallback so chatbot works immediately
- Generates answers with Gemini
"""

import hashlib
import json
import os
import math
import re
import time
import pickle
import threading
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai

from agents import fare_lookup

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CHUNKS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "rag" / "outputs" / "chunked_documents.jsonl"
)
CACHE_PATH = (
    Path(__file__).resolve().parent.parent
    / "models" / "rag_embeddings_cache.pkl"
)

GEMINI_MODEL   = "models/gemini-flash-lite-latest"
# Free-tier embed quota is PER MODEL and per day (each text in a batch counts
# as one request), so the model choice doubles as the quota bucket. The build
# checkpoints progress and resumes across days if the corpus outsizes a bucket.
EMBED_MODEL    = "models/gemini-embedding-2"

_chunks: list[dict] = []
_embeddings: list[list[float]] = []
_ready = False
_embed_attempted = False   # don't retry if quota is dead
_lock = threading.Lock()


def _load_chunks():
    global _chunks
    if _chunks:
        return
    with CHUNKS_PATH.open("r", encoding="utf-8") as f:
        _chunks = [json.loads(line) for line in f if line.strip()]


def _corpus_fingerprint() -> str:
    """SHA-256 of the chunk file, so a re-chunked corpus invalidates the cache."""
    h = hashlib.sha256()
    with CHUNKS_PATH.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _build_embeddings_bg():
    """Runs in a daemon thread — builds cache without blocking any request."""
    global _chunks, _embeddings, _ready, _embed_attempted

    with _lock:
        if _embed_attempted:
            return
        _embed_attempted = True

    try:
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        _load_chunks()

        fingerprint = _corpus_fingerprint()
        partial_path = CACHE_PATH.with_suffix(".partial.pkl")

        # 50 texts/batch stays inside the free-tier per-minute request+token
        # windows (90 was borderline and 429'd persistently).
        batch_size = 50
        embeddings_tmp = []
        start = 0

        # Resume a previous run that died on quota — don't re-pay for done batches.
        if partial_path.exists():
            try:
                with partial_path.open("rb") as f:
                    partial = pickle.load(f)
                if (partial.get("fingerprint") == fingerprint
                        and partial.get("model") == EMBED_MODEL):
                    embeddings_tmp = partial["embeddings"]
                    start = len(embeddings_tmp)
                    print(f"[RAG] Resuming embedding from {start}/{len(_chunks)}")
                else:
                    partial_path.unlink()
            except Exception:
                pass

        print(f"[RAG] Embedding {len(_chunks)} chunks in background (will cache)...")

        for i in range(start, len(_chunks), batch_size):
            batch = _chunks[i: i + batch_size]
            texts = [c["text"] for c in batch]

            max_retries = 4
            for attempt in range(max_retries):
                try:
                    result = genai.embed_content(
                        model=EMBED_MODEL, content=texts,
                        task_type="retrieval_document",
                        request_options={"timeout": 120},  # a hung call must not stall the whole build
                    )
                    embeddings_tmp.extend(result["embedding"])
                    print(f"[RAG] Embedded {min(i+batch_size, len(_chunks))}/{len(_chunks)}")
                    # checkpoint so a quota death resumes instead of restarting
                    partial_path.parent.mkdir(parents=True, exist_ok=True)
                    with partial_path.open("wb") as f:
                        pickle.dump({"fingerprint": fingerprint,
                                     "model": EMBED_MODEL,
                                     "embeddings": embeddings_tmp}, f)
                    break
                except Exception as e:
                    if "429" in str(e) or "quota" in str(e).lower():
                        # A DAILY quota can't be waited out — retrying just burns
                        # tomorrow's budget (every text in the batch counts).
                        if "PerDay" in str(e):
                            print(f"[RAG] Daily embed quota reached — progress saved at "
                                  f"{len(embeddings_tmp)}/{len(_chunks)}; resumes on next "
                                  f"backend start. Keyword fallback active.")
                            return
                        if attempt < max_retries - 1:
                            wait = 65
                            print(f"[RAG] Rate limit — waiting {wait}s (attempt {attempt+1}/{max_retries})...")
                            time.sleep(wait)
                        else:
                            print(f"[RAG] Quota exhausted after max retries — progress saved at "
                                  f"{len(embeddings_tmp)}/{len(_chunks)}; will resume next start. "
                                  f"Keyword fallback active. Last error: {str(e)[:300]}")
                            return
                    else:
                        print(f"[RAG] Embedding error: {e}")
                        return

            if i + batch_size < len(_chunks):
                time.sleep(62)

        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CACHE_PATH.open("wb") as f:
            pickle.dump({
                "chunks": _chunks,
                "embeddings": embeddings_tmp,
                "fingerprint": fingerprint,
                "model": EMBED_MODEL,
            }, f)
        partial_path.unlink(missing_ok=True)

        with _lock:
            _embeddings[:] = embeddings_tmp
            global _ready
            _ready = True
        print(f"[RAG] Cache saved → {CACHE_PATH}. Semantic search now active.")

    except Exception as e:
        print(f"[RAG] Background embedding failed: {e}")


def _load_valid_cache() -> dict | None:
    """Return the cached dict only if it was built from the current corpus."""
    try:
        with CACHE_PATH.open("rb") as f:
            cached = pickle.load(f)
    except Exception as e:
        print(f"[RAG] Cache unreadable ({e}) — will re-embed.")
        return None
    if (cached.get("fingerprint") != _corpus_fingerprint()
            or cached.get("model") != EMBED_MODEL):
        print("[RAG] Corpus or embedding model changed since cache was built — re-embedding...")
        return None
    return cached


def _load_from_cache(cached: dict):
    """Activate a pre-built, validated cache (fast — already unpickled)."""
    global _chunks, _embeddings, _ready
    _embeddings = cached["embeddings"]
    _chunks     = cached["chunks"]
    _ready = True
    print(f"[RAG] {len(_embeddings)} embeddings loaded. Semantic search active.")


def _ensure_started():
    """Called once per process. Loads cache if ready, else starts bg thread."""
    global _embed_attempted
    if _ready:
        return
    if CACHE_PATH.exists():
        cached = _load_valid_cache()
        if cached is not None:
            _load_from_cache(cached)
            return
        CACHE_PATH.unlink(missing_ok=True)  # stale — rebuild below
    # No cache yet — kick off background embedding (daemon so it won't block shutdown)
    with _lock:
        if not _embed_attempted:
            t = threading.Thread(target=_build_embeddings_bg, daemon=True, name="rag-embed")
            t.start()


def _keyword_retrieve(question: str, top_k: int) -> list[dict]:
    """
    Keyword fallback with synonym expansion so common transit terms
    still match relevant chunks even without embeddings.
    """
    _load_chunks()

    # Synonym map: query word → additional words to also match
    SYNONYMS: dict[str, list[str]] = {
        "breakdown":   ["disruption", "fault", "failure", "breakdown", "malfunction", "stopped"],
        "delay":       ["delayed", "late", "slow", "disruption", "waiting"],
        "disruption":  ["breakdown", "delay", "fault", "service", "disrupted"],
        "passenger":   ["commuter", "rider", "traveller", "customer"],
        "refund":      ["compensation", "refund", "reimburse", "claim"],
        "fare":        ["price", "ticket", "cost", "fee", "charge", "pass"],
        "pass":        ["card", "token", "touch", "monthly", "unlimited"],
        "operating":   ["hours", "schedule", "time", "open", "closing"],
        "bicycle":     ["bike", "cycle", "bicycle"],
        "guideline":   ["guide", "rule", "policy", "procedure", "advisory"],
        "complaint":   ["feedback", "complaint", "report", "contact"],
    }

    q_lower = question.lower()
    q_words = set(q_lower.split())

    # Expand with synonyms
    expanded = set(q_words)
    for word in list(q_words):
        # Strip punctuation from word
        clean = word.strip("?.,!\"'")
        for key, syns in SYNONYMS.items():
            if clean == key or clean in syns:
                expanded.update(syns)
                expanded.add(key)

    # Filter out stop words
    stop = {"the","a","an","is","are","was","were","be","been","being","have",
            "has","had","do","does","did","will","would","could","should","may",
            "might","shall","can","to","of","in","for","on","with","at","by",
            "from","about","into","through","during","what","how","when","where",
            "who","which","and","or","but","if","not","i","my","your","their",
            "we","us","me","it","its","this","that","these","those","please"}
    expanded -= stop
    base = {w.strip("?.,!\"'") for w in q_words} - stop  # the user's own words
    base = {w for w in base if w}
    expanded -= base

    # The user's own words (station names, specific terms) weigh 3× more than
    # synonym expansions — otherwise generic fare/pass synonyms drown out a
    # "Gombak to Kajang" match.
    scored = []
    for chunk in _chunks:
        text = chunk.get("text", "").lower()
        score = (3 * sum(1 for w in base if w in text)
                 + sum(1 for w in expanded if w in text))
        scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]


def _cosine(a: list[float], b: list[float]) -> float:
    dot   = sum(x*y for x,y in zip(a,b))
    mag_a = math.sqrt(sum(x*x for x in a))
    mag_b = math.sqrt(sum(x*x for x in b))
    return dot / (mag_a * mag_b) if mag_a and mag_b else 0.0


def _pgvector_retrieve(question: str, top_k: int) -> list[dict]:
    """Semantic retrieval from the canonical pgvector store (Supabase).
    Used when the local cache is not ready — e.g. a fresh machine before the
    first embedding build. Returns [] on any failure so keyword fallback
    still applies (and the offline test suite never touches the network)."""
    try:
        from db.supabase_client import _get_client
        sb = _get_client()
        if sb is None:
            return []
        qr = genai.embed_content(model=EMBED_MODEL, content=question,
                                 task_type="retrieval_query",
                                 request_options={"timeout": 30})
        emb = "[" + ",".join(f"{v:.7f}" for v in qr["embedding"]) + "]"
        res = sb.rpc("match_rag_chunks",
                     {"query_embedding": emb, "match_count": top_k}).execute()
        return [{"source_file": r["source_file"], "text": r["content"]}
                for r in (res.data or [])]
    except Exception as e:
        print(f"[RAG] pgvector retrieval unavailable: {e}")
        return []


def _embedding_retrieve(question: str, top_k: int) -> list[dict]:
    qr = genai.embed_content(model=EMBED_MODEL, content=question,
                             task_type="retrieval_query",
                             request_options={"timeout": 15})
    qe = qr["embedding"]
    scored = [(_cosine(qe, emb), chunk) for emb, chunk in zip(_embeddings, _chunks)]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]


def _extractive_answer(question: str, top_chunks: list[dict]) -> str:
    """Generation-free answer: return the most question-relevant sentences from
    the top retrieved chunk verbatim. Used when Gemini generation is
    unavailable (quota/latency) so the chatbot stays useful, not broken."""
    if not top_chunks:
        return ("I couldn't find this in the official Rapid KL documents I have. "
                "Please rephrase, or check myrapid.com.my.")

    stop = {"the","a","an","is","are","what","how","much","do","does","of","to",
            "for","in","on","and","or","my","i","you","can","when","where","which"}
    q_words = {w.strip("?.,!\"'").lower() for w in question.split()} - stop
    q_words = {w for w in q_words if len(w) > 2}

    # Find the chunk + character offset with the strongest keyword overlap, then
    # return a window of text FROM that point forward (so an answer that follows
    # a matching heading like "What is My50?" is captured, not just the heading).
    best_chunk, best_pos, best_score = top_chunks[0], 0, -1
    for chunk in top_chunks[:3]:
        text = chunk.get("text", "")
        low = text.lower()
        for m in re.finditer(r"\S+", low):
            w = m.group(0).strip("?.,!\"':")
            if w not in q_words:
                continue
            window = low[m.start(): m.start() + 300]
            score = sum(1 for qw in q_words if qw in window)
            if score > best_score:
                best_score, best_chunk, best_pos = score, chunk, m.start()

    text = best_chunk.get("text", "")
    excerpt = text[best_pos: best_pos + 480].strip()
    # trim a trailing partial sentence for readability
    if "." in excerpt[60:]:
        excerpt = excerpt[: excerpt.rfind(".") + 1]
    src = best_chunk.get("source_file", "an official Rapid KL document")
    return (f"{excerpt}\n\n(Quoted directly from {src}. The AI summariser is "
            f"temporarily unavailable, so this is the exact document text.)")


# Product and pass names that appear throughout the corpus. A typo in one of
# these is fatal to retrieval-then-generation: the right document is still
# fetched (the surrounding words match), but the generator finds no "my53" in
# it and honestly reports it knows nothing — so the user is refused an answer
# the corpus plainly contains.
#
# The list is bounded and known, which is exactly the case where correcting by
# similarity beats asking a model to guess: it is instant, free, and cannot
# invent a pass that does not exist.
_KNOWN_TERMS = (
    "my50", "mutiara", "bulanan", "kembara", "kota", "mesra", "emas",
    "keluarga", "pelajar", "mytentera", "mykad", "concession", "touch n go",
)
# Similarity needed to accept a correction. Short names cannot reach a high
# ratio from a single wrong character — "my53" against "my50" is only 75 — so
# the bar scales with length.
def _term_cutoff(term: str) -> float:
    return 75.0 if len(term) <= 5 else 76.0


# Everyday words that score above the cutoff against a product name and would
# otherwise be rewritten mid-question. "kotak" (box) reaches 89 against "kota"
# and "kita" (we) reaches 75 — both are ordinary Malay a commuter types.
# Measured, not guessed: these are the only collisions found across a list of
# common EN/BM words.
_NEVER_CORRECT = {
    "kita", "kotak", "kereta", "kelas", "kecil", "kemas", "kosong", "kuat",
    "kertas", "masa", "mesin", "meja", "muka", "peta", "pergi", "pintu",
    "pusat", "balik", "besar", "boleh", "buka", "buku", "kata", "kota",
    "cost", "most", "must", "make", "take", "keep", "kept", "money",
}


def _correct_terms(question: str) -> tuple[str, list[tuple[str, str]]]:
    """Fix near-miss product names. Returns (corrected_question, [(was, now)]).

    Only tokens that ALREADY look like one of these terms are touched — a
    shared prefix plus a similar shape — so ordinary words are left alone.
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        return question, []

    fixes: list[tuple[str, str]] = []

    def repl(m: re.Match) -> str:
        word = m.group(0)
        low = word.lower()
        if low in _KNOWN_TERMS or low in _NEVER_CORRECT:
            return word
        best, best_score = None, 0.0
        for term in _KNOWN_TERMS:
            if " " in term:
                continue
            # A ONE-character prefix match. Two characters blocked the most
            # common error in Malay words — a substituted vowel — so "motira"
            # (mutiara) and "kumbara" (kembara) were never corrected despite
            # scoring 77 and 86. Safety comes from _NEVER_CORRECT instead.
            if term[:1] != low[:1]:
                continue
            score = fuzz.ratio(low, term)
            if score > best_score:
                best, best_score = term, score
        if best and best_score >= _term_cutoff(best):
            fixes.append((word, best))
            return best
        return word

    # Speech and casual typing split the name: "my 53 watt is" instead of
    # "my53 what is". Rejoin it so the token below has something to match.
    question = re.sub(r"\bmy\s+(\d{2})\b", r"my\1", question, flags=re.I)

    corrected = re.sub(r"[A-Za-z][A-Za-z0-9']{2,}", repl, question)
    return corrected, fixes


def answer(question: str, top_k: int = 5, history: list[dict] | None = None) -> dict:
    """
    Answer a question using RAG retrieval + Gemini generation.

    Args:
        question:  The current user question.
        top_k:     Number of context chunks to retrieve.
        history:   Prior turns as [{"role": "user"|"assistant", "text": "..."}]
    """
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

    # Fix typos in the bounded set of product names BEFORE anything else.
    # Retrieval survives a typo (the surrounding words still match, which is
    # why "my53" still cited the My50 FAQ) but generation does not: the term
    # is absent from the retrieved text, so the model correctly reports it
    # knows nothing — refusing an answer the corpus plainly contains.
    question, _corrections = _correct_terms(question)

    # Exact station-pair fare questions are answered straight from the
    # validated fare matrices — deterministic, no retrieval, no LLM, so a
    # wrong-origin chunk can never ground a wrong number.
    fare_answer = fare_lookup.try_answer(question)
    if fare_answer:
        return {
            "answer":      fare_answer,
            "sources":     ["integrated_fare_table (validated matrix)"],
            "chunks_used": 0,
            "mode":        "fare_lookup",
        }

    # Start cache load / background embedding if not done yet (non-blocking)
    _ensure_started()

    if _ready:
        top_chunks = _embedding_retrieve(question, top_k)   # local cache (fast path)
        mode = "semantic"
    else:
        top_chunks = _pgvector_retrieve(question, top_k)    # canonical pgvector store
        mode = "semantic_pgvector"
        if not top_chunks:
            top_chunks = _keyword_retrieve(question, top_k) # offline last resort
            mode = "keyword"

    context = "\n\n---\n\n".join(
        f"[Source: {c.get('source_file','unknown')}]\n{c['text']}"
        for c in top_chunks
    )

    # Build conversation history block
    history_block = ""
    if history:
        turns = []
        for turn in history[-6:]:   # keep last 6 turns to stay within token budget
            role = "User" if turn.get("role") == "user" else "Assistant"
            turns.append(f"{role}: {turn.get('text', '')}")
        history_block = "\n\nPrevious conversation:\n" + "\n".join(turns)

    model = genai.GenerativeModel(GEMINI_MODEL)
    prompt = f"""You are an AI assistant for Rapid KL / Prasarana LRT services in Malaysia.
Answer the user's question using ONLY the context below.
If the answer is not in the context, say "I don't have that information in my knowledge base."

Answer format rules (the app serves commuters of all ages, including elderly users):
- Lead with the direct answer in the FIRST sentence — no preamble, no restating the question.
- Maximum 3 short sentences for simple questions.
- If listing steps or options, use short bullet points (max 5 words each where possible).
- Use plain everyday words. Avoid jargon and long clauses.
- Bold the single most important fact (a price, a time, a station name) using **markdown**.
- Reply in the language the question is WRITTEN in: English question means English
  answer, Malay question means Malay answer. Malay station or place names inside
  an English question do NOT make it a Malay question.

Context:
{context}{history_block}

Current question: {question}

Answer:"""

    sources = list({c.get("source_file", "unknown") for c in top_chunks})

    # Generation is the one remote step left. If Gemini is slow or unavailable
    # (504 deadline, quota, network) we must NOT 500 the request — retrieval
    # already succeeded, so return an honest degraded answer that still points
    # the user at the right official documents.
    try:
        response = model.generate_content(prompt, request_options={"timeout": 15})
        answer = (response.text or "").strip()
        if not answer:
            raise ValueError("empty generation")
    except Exception as e:
        # Generation is down (commonly free-tier quota exhaustion, seen as a
        # 429 or a slow 504). Retrieval still succeeded, so fall back to an
        # EXTRACTIVE answer: return the most relevant official-document text
        # directly instead of a generated summary. Honest and still useful.
        print(f"[RAG] generation failed ({type(e).__name__}) — extractive fallback")
        answer = _extractive_answer(question, top_chunks)
        mode = f"{mode}_extractive"

    return {
        # Say what was silently changed. A corrected question that returns a
        # confident answer about a DIFFERENT product is worse than a refusal
        # if the user never learns the substitution happened.
        "answer":      (answer if not _corrections else
                        "*Showing results for "
                        + ", ".join(now for _, now in _corrections)
                        + ".*\n\n" + answer),
        "sources":     sources,
        "chunks_used": top_k,
        "mode":        mode,
        "corrections": _corrections,
    }
