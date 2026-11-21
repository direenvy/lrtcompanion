"""
Supabase logging client.
All functions are fire-and-forget — errors are caught and printed, never raised,
so a DB outage never breaks the API.
"""
from datetime import datetime, timezone

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_client = None


def _get_client():
    """Backend Supabase client — prefers service-role key so RLS doesn't block writes."""
    global _client
    if _client is None:
        try:
            from supabase import create_client
            url = os.getenv("SUPABASE_URL", "")
            # Service key bypasses RLS; fall back to anon key if not configured.
            key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY", "")
            if url and key:
                _client = create_client(url, key)
        except Exception as e:
            print(f"[Supabase] Init failed: {e}")
    return _client


def log_disruption(text: str, sentiment: str, issue_type: str, disruption_alert: bool,
                   source: str = "user", method: str | None = None,
                   created_at: str | None = None):
    """source: 'user' (in-app report) or 'x_live' (X API ingestion).
    method:  'local' (TF-IDF + LogReg kept the label) or 'gemini_fallback'
             (low-confidence escalation overrode it) — from predict()['method'].
    created_at: ISO timestamp override (e.g. the tweet's own timestamp)."""
    from agents.net_guard import is_offline, mark_offline, mark_online
    if is_offline():
        return          # best-effort logging; never worth a timeout
    try:
        sb = _get_client()
        if sb:
            row = {
                "text":             text[:500],
                "sentiment":        sentiment,
                "issue_type":       issue_type,
                "disruption_alert": disruption_alert,
                "source":           source,
            }
            if method is not None:
                row["method"] = method
            if created_at:
                row["created_at"] = created_at
            sb.table("disruption_logs").insert(row).execute()
        mark_online()
    except Exception as e:
        mark_offline()
        print(f"[Supabase] log_disruption failed: {e}")


def log_chat(question: str, answer: str, mode: str, grounding: str | None = None):
    """grounding: the verification verdict for this answer — 'supported',
    'partial', 'unsupported', 'unchecked' or 'skipped'. Accumulating it turns a
    one-off adversarial test into an ongoing groundedness measurement."""
    try:
        sb = _get_client()
        if sb:
            row = {
                "question": question[:500],
                "answer":   answer[:2000],
                "mode":     mode,
            }
            if grounding:
                row["grounding"] = grounding
            try:
                sb.table("chat_logs").insert(row).execute()
            except Exception:
                # The grounding column is newer than this table. Rather than
                # lose the whole log row on a schema that predates it, drop the
                # field and retry — see db/create_tables.sql for the migration.
                if "grounding" not in row:
                    raise
                row.pop("grounding")
                sb.table("chat_logs").insert(row).execute()
                print("[Supabase] chat_logs has no 'grounding' column — logged without it")
    except Exception as e:
        print(f"[Supabase] log_chat failed: {e}")


def log_feedback(question: str, answer: str, rating: int):
    """rating: 1 = thumbs up, -1 = thumbs down"""
    try:
        sb = _get_client()
        if sb:
            sb.table("feedback_logs").insert({
                "question": question[:500],
                "answer":   answer[:2000],
                "rating":   rating,
            }).execute()
    except Exception as e:
        print(f"[Supabase] log_feedback failed: {e}")


# ── Live-ingestion cursor ─────────────────────────────────────────────────────
# The cursor used to live in a JSON file on the container's own disk. That was
# fine on an always-on instance and is wrong on one that sleeps: the file goes
# with the container, so every wake re-fetches tweets already processed, burns
# the monthly quota and writes duplicate rows. A redeploy did the same on any
# tier.
#
# Both functions are best-effort by design. load returns None when the row or
# the table is unavailable, and the caller falls back to the local file, so a
# Supabase outage degrades ingestion to the old behaviour instead of stopping
# it. See db/create_tables.sql for the table.
INGEST_STATE_ID = 1


def load_ingest_state() -> dict | None:
    """The stored cursor, or None if it cannot be read."""
    try:
        sb = _get_client()
        if not sb:
            return None
        res = (sb.table("ingest_state").select("*")
                 .eq("id", INGEST_STATE_ID).limit(1).execute())
        rows = res.data or []
        if not rows:
            return None
        row = rows[0]
        seen = row.get("seen_ids")
        return {
            "seen_ids": seen if isinstance(seen, list) else [],
            "newest_id": row.get("newest_id"),
            "last_poll": row.get("last_poll"),
            "last_result": row.get("last_result"),
            "tweets_scanned": row.get("tweets_scanned") or 0,
            "alerts_raised": row.get("alerts_raised") or 0,
            "alerts_gated": row.get("alerts_gated") or 0,
        }
    except Exception as e:
        print(f"[Supabase] ingest_state read failed ({type(e).__name__}) — "
              f"falling back to the local file")
        return None


def save_ingest_state(state: dict) -> bool:
    """Persist the cursor. True if it was written."""
    try:
        sb = _get_client()
        if not sb:
            return False
        row = {
            "id": INGEST_STATE_ID,
            "newest_id": state.get("newest_id"),
            "seen_ids": state.get("seen_ids") or [],
            "last_poll": state.get("last_poll"),
            "last_result": state.get("last_result"),
            "tweets_scanned": state.get("tweets_scanned") or 0,
            "alerts_raised": state.get("alerts_raised") or 0,
            "alerts_gated": state.get("alerts_gated") or 0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        sb.table("ingest_state").upsert(row, on_conflict="id").execute()
        return True
    except Exception as e:
        print(f"[Supabase] ingest_state write failed ({type(e).__name__}) — "
              f"the local file still holds the cursor")
        return False
