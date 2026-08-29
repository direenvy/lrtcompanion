"""
Supabase logging client.
All functions are fire-and-forget — errors are caught and printed, never raised,
so a DB outage never breaks the API.
"""

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


def log_chat(question: str, answer: str, mode: str):
    try:
        sb = _get_client()
        if sb:
            sb.table("chat_logs").insert({
                "question": question[:500],
                "answer":   answer[:2000],
                "mode":     mode,
            }).execute()
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
