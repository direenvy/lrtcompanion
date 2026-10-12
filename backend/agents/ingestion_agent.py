"""
Live Ingestion Agent — polls external sources for Klang Valley rail chatter,
classifies each post through the existing NLP pipeline, and logs disruption
alerts into disruption_logs tagged with their source (e.g. "x_live").

Design rules (see LIVE_DATA_PLAN.md):
- Pluggable sources: each source is a fetch function returning normalised
  posts; adding Reddit later means adding one fetch function, zero pipeline
  changes.
- Deduplicate by post ID — a post is never classified twice, across restarts.
- Rate-limit aware: HTTP 429 backs off and reports honestly; X errors never
  crash the API.
- The bearer token is read at call time from the environment, never at import.
"""

import csv
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from agents.nlp_agent import predict
from db.supabase_client import log_disruption

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Config ────────────────────────────────────────────────────────────────────
POLL_INTERVAL_MINUTES = 30          # LIVE_DATA_PLAN B1: every 20–30 min
MAX_RESULTS_PER_POLL  = 10          # keep well inside the 10k tweets/month quota
X_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
# NOTE: X's language codes: Indonesian/Malay tweets are labelled 'id'
# ('in' and 'ms' are NOT valid specifiers and cause HTTP 400).
#
# Query design: bare "lrt" on English X is slang ("last retweet") and "mrt"
# matches Jakarta/Singapore — so generic transit words only count WITH a
# Malaysia-context word, while unambiguous brand terms stand alone.
# from:AskRapidKL (official service announcements) sits OUTSIDE the language
# filter — X's tagger is unreliable on Malay, and an official alert must never
# be dropped over a bad language guess.
#
# Malay arm: also language-filter-free, because short/rojak Malay tweets are
# often tagged 'und' and would be dropped. Vocabulary is distinctively
# Malaysian Malay — 'rosak'/'tergendala' (Indonesian: 'rusak'/'terkendala') —
# so it self-identifies without a lang: clause. Any residual Jakarta noise is
# filtered downstream: the NLP classifier + line attribution only raise alerts
# that map to a Malaysian line.
X_QUERY = ('(from:AskRapidKL OR '
           '((rapidkl OR "rapid kl" OR lrt3 OR "shah alam line" OR myrapid '
           'OR ((lrt OR mrt OR monorail OR ktm) '
           '("kuala lumpur" OR malaysia OR "kelana jaya" OR ampang OR kajang '
           'OR putrajaya OR "bandar utama" OR klcc OR "kl sentral")) '
           ') (lang:en OR lang:id)) OR '
           '((lrt OR mrt OR monorail OR komuter OR tren) '
           '(rosak OR tergendala OR terganggu OR sesak OR "tak bergerak" OR tersadai) '
           '-jakarta -transjakarta -jabodetabek -palembang)'
           ') -is:retweet')

# The official Rapid KL service account — its posts are authoritative, so a
# single official announcement confirms a disruption on its own (see the
# source-weighted corroboration in api/dashboard.py).
OFFICIAL_ACCOUNT = "AskRapidKL"

STATE_PATH = Path(__file__).resolve().parent.parent / "models" / "x_ingest_state.json"
MAX_SEEN_IDS = 2000                 # enough for months of polling at 10/poll

# Every scanned tweet (alert or not) is appended here with its prediction so
# the live-labelling pass (LIVE_DATA_PLAN Part C) has raw material: a human
# fills the empty sentiment/issue_type columns, then merge_and_retrain.py
# consumes the file. Local research file only — never served or redistributed.
LABELLING_CSV = (Path(__file__).resolve().parent.parent.parent
                 / "data" / "nlp" / "interim" / "live_x_labelling.csv")

# X occasionally returns transient 5xx (503 Service Unavailable) during upstream
# blips. These are retryable — a short in-poll backoff avoids losing a whole
# 30-min cycle to a momentary outage. 429 (rate limit) is handled separately.
RETRY_STATUSES = frozenset({500, 502, 503, 504})
RETRY_BACKOFF_SECONDS = (2.0, 5.0)  # delays between attempts; len == max retries
_sleep = time.sleep                  # indirection so tests run instantly

_lock = threading.Lock()
_poll_thread: threading.Thread | None = None


# ── State (survives restarts so posts are never classified twice) ─────────────
def _load_state() -> dict:
    try:
        with STATE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"seen_ids": [], "newest_id": None, "last_poll": None,
                "tweets_scanned": 0, "alerts_raised": 0, "last_result": None}


def _save_state(state: dict) -> None:
    state["seen_ids"] = state["seen_ids"][-MAX_SEEN_IDS:]
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f)


# ── Sources (pluggable: each returns a list of normalised posts) ──────────────
def _http_get_json(url: str, headers: dict) -> dict:
    """Isolated so tests can monkeypatch it. Raises urllib.error.HTTPError."""
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_x(since_id: str | None = None) -> list[dict]:
    """Fetch recent matching tweets. Returns [{id, text, created_at}, ...].
    Raises RateLimited on HTTP 429; RuntimeError on other failures."""
    token = os.getenv("X_BEARER_TOKEN", "").strip()
    if not token:
        raise RuntimeError("X_BEARER_TOKEN not configured")

    params = {
        "query": X_QUERY,
        "max_results": str(MAX_RESULTS_PER_POLL),
        "tweet.fields": "created_at,lang",
        # author info so we can flag official @AskRapidKL posts as authoritative
        "expansions": "author_id",
        "user.fields": "username",
    }
    if since_id:
        params["since_id"] = since_id
    url = f"{X_SEARCH_URL}?{urllib.parse.urlencode(params)}"

    headers = {"Authorization": f"Bearer {token}"}
    for attempt in range(len(RETRY_BACKOFF_SECONDS) + 1):
        try:
            data = _http_get_json(url, headers)
            break
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "ignore")[:300]
            except Exception:
                detail = ""
            if e.code == 429:
                raise RateLimited("X API rate limit (HTTP 429)") from e
            if e.code == 400 and "since_id" in detail:
                raise StaleCursor(detail) from e
            if e.code in RETRY_STATUSES and attempt < len(RETRY_BACKOFF_SECONDS):
                _sleep(RETRY_BACKOFF_SECONDS[attempt])
                continue
            raise RuntimeError(f"X API error: HTTP {e.code} {detail}") from e
        except urllib.error.URLError as e:
            if attempt < len(RETRY_BACKOFF_SECONDS):
                _sleep(RETRY_BACKOFF_SECONDS[attempt])
                continue
            raise RuntimeError(f"X API unreachable: {e.reason}") from e

    # Map author_id -> username so we can flag official Rapid KL announcements
    users = {u["id"]: u.get("username", "").lower()
             for u in data.get("includes", {}).get("users", [])}
    return [
        {"id": t["id"], "text": t.get("text", ""),
         "created_at": t.get("created_at"),
         "official": users.get(t.get("author_id")) == OFFICIAL_ACCOUNT.lower()}
        for t in data.get("data", [])
    ]


class RateLimited(Exception):
    pass


class StaleCursor(RuntimeError):
    """since_id is older than X's 7-day recent-search window.

    X rejects such a cursor with HTTP 400 rather than ignoring it, so the
    stored newest_id has to be dropped — otherwise every later poll resends
    the same dead id and ingestion never recovers from a gap of over a week.
    Subclasses RuntimeError so it is still handled as a poll failure if the
    recovery in _fetch_with_cursor_reset is ever removed.
    """


def _fetch_with_cursor_reset(state: dict) -> list[dict]:
    """fetch_x, recovering once from a cursor X no longer accepts.

    Mutates state["newest_id"] to None on reset; the caller persists state on
    every path, so the dead cursor is cleared even if the retry itself fails.
    """
    try:
        return fetch_x(since_id=state.get("newest_id"))
    except StaleCursor as e:
        print(f"[Ingest] since_id stale, dropping cursor and refetching: {e}")
        state["newest_id"] = None
        return fetch_x(since_id=None)


def _append_labelling_rows(rows: list[dict]) -> None:
    """Append scanned tweets + predictions to the live-labelling sheet.
    Best-effort: a filesystem problem must never break a poll."""
    if not rows:
        return
    try:
        LABELLING_CSV.parent.mkdir(parents=True, exist_ok=True)
        new_file = not LABELLING_CSV.exists()
        with LABELLING_CSV.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "id", "created_at", "cleaned_text",
                "pred_sentiment", "pred_issue", "pred_method",
                "sent_conf", "issue_conf", "disruption_alert",
                "sentiment", "issue_type",     # ← empty: filled by the human
            ])
            if new_file:
                w.writeheader()
            w.writerows(rows)
    except Exception as e:
        print(f"[Ingest] labelling capture failed (non-fatal): {e}")


# ── Pipeline ──────────────────────────────────────────────────────────────────
def run_pull() -> dict:
    """One poll cycle: fetch → dedupe → classify → log alerts. Never raises."""
    with _lock:
        state = _load_state()
        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            posts = _fetch_with_cursor_reset(state)
        except RateLimited as e:
            state["last_poll"] = now_iso
            state["last_result"] = "rate_limited"
            _save_state(state)
            return {"status": "rate_limited", "detail": str(e),
                    "scanned": 0, "alerts": 0}
        except RuntimeError as e:
            state["last_poll"] = now_iso
            state["last_result"] = f"error: {e}"
            _save_state(state)
            return {"status": "error", "detail": str(e), "scanned": 0, "alerts": 0}

        seen = set(state["seen_ids"])
        new_posts = [p for p in posts if p["id"] not in seen]

        alerts = 0
        labelling_rows = []
        for post in new_posts:
            result = predict(post["text"])
            if result["disruption_alert"]:
                log_disruption(
                    text=post["text"],
                    sentiment=result["sentiment"],
                    issue_type=result["issue_type"],
                    disruption_alert=True,
                    # official Rapid KL posts are authoritative → x_official
                    # (confirms on its own); other tweets stay x_live (low-trust)
                    source="x_official" if post.get("official") else "x_live",
                    method=result.get("method"),
                    created_at=post.get("created_at"),
                )
                alerts += 1
            labelling_rows.append({
                "id": post["id"], "created_at": post.get("created_at", ""),
                "cleaned_text": " ".join(post["text"].split()),
                "pred_sentiment": result.get("sentiment", ""),
                "pred_issue": result.get("issue_type", ""),
                "pred_method": result.get("method", ""),
                "sent_conf": max(result.get("sentiment_scores", {}).values(), default=""),
                "issue_conf": max(result.get("issue_scores", {}).values(), default=""),
                "disruption_alert": result.get("disruption_alert", False),
                "sentiment": "", "issue_type": "",
            })
            state["seen_ids"].append(post["id"])
        _append_labelling_rows(labelling_rows)

        if posts:
            newest = max(int(p["id"]) for p in posts)
            if state.get("newest_id"):
                newest = max(newest, int(state["newest_id"]))
            state["newest_id"] = str(newest)
        state["last_poll"] = now_iso
        state["tweets_scanned"] = state.get("tweets_scanned", 0) + len(new_posts)
        state["alerts_raised"] = state.get("alerts_raised", 0) + alerts
        state["last_result"] = "ok"
        _save_state(state)

        return {"status": "ok", "scanned": len(new_posts), "alerts": alerts}


def get_status() -> dict:
    """Honest counters for the dashboard tile — no fake activity."""
    state = _load_state()
    return {
        "configured": bool(os.getenv("X_BEARER_TOKEN", "").strip()),
        "poll_interval_minutes": POLL_INTERVAL_MINUTES,
        "last_poll": state.get("last_poll"),
        "last_result": state.get("last_result"),
        "tweets_scanned": state.get("tweets_scanned", 0),
        "alerts_raised": state.get("alerts_raised", 0),
    }


# ── Background poller ─────────────────────────────────────────────────────────
def _poll_loop():
    while True:
        summary = run_pull()
        print(f"[Ingest] Poll: {summary}")
        wait = POLL_INTERVAL_MINUTES * 60
        if summary["status"] == "rate_limited":
            wait *= 2  # back off
        time.sleep(wait)


def start_polling() -> bool:
    """Start the poller thread if a token is configured. Returns True if started."""
    global _poll_thread
    if not os.getenv("X_BEARER_TOKEN", "").strip():
        print("[Ingest] X_BEARER_TOKEN not set — live ingestion inactive.")
        return False
    if _poll_thread and _poll_thread.is_alive():
        return True
    _poll_thread = threading.Thread(target=_poll_loop, daemon=True, name="x-ingest")
    _poll_thread.start()
    print(f"[Ingest] Live X polling started (every {POLL_INTERVAL_MINUTES} min).")
    return True
