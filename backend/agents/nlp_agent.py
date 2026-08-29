"""
NLP Early Warning Agent
Primary: TF-IDF + Logistic Regression (fast, offline)
Fallback: Gemini LLM classification when model confidence < 60%

This hybrid approach gives the best of both worlds — instant local
inference for clear-cut cases, LLM accuracy for ambiguous ones.
"""

import os
import re
import json
import joblib
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

# Confidence thresholds below which Gemini is used as fallback.
# Sentiment has 3 classes (easier to hit 60%); issue_type has 7 (max prob spreads thinner).
SENT_THRESHOLD  = 60.0
ISSUE_THRESHOLD = 40.0

# ── Ticketing / equipment guard ──────────────────────────────────────────────
# Announcements about token machines, ticket counters, card readers or fare
# gates are NOT train-service breakdowns — the trains keep running. Left as
# 'breakdown' they trip the disruption-alert rule, and an OFFICIAL such post
# (source weight 2.0) confirms a line INSTANTLY, falsely cutting it from the
# routing graph while service is normal. When the text is clearly about
# ticketing/equipment and shows no sign of a train-movement problem, the issue
# is downgraded to 'information' so the alert never fires.
_TICKETING_TERMS = (
    "otp", "office ticket processor", "token", "ticket machine", "ticketing",
    "ticket counter", "counter", "kaunter", "vending", "card reader",
    "fare gate", "faregate", "touch n go", "touch 'n go", "top up", "top-up",
    "reload",
)
# If ANY of these appear, the post plausibly describes a genuine service
# problem, so the guard stands down and the model's label is kept.
_TRAIN_TROUBLE_TERMS = (
    "stuck", "stranded", "terkandas", "terperangkap",
    "not moving", "tak bergerak", "tak gerak",
    "broke down", "broken down", "breakdown", "rosak", "kerosakan",
    "derail", "evacuat", "emergency brake",
    "platform", "no train", "tiada tren", "train accident",
)


def _is_ticketing_only(text: str) -> bool:
    """True when the text is about a ticketing/equipment outage (token machines,
    counters, card readers, fare gates) and carries NO sign of a train-movement
    problem — in which case it must not be flagged as a service breakdown."""
    lower = f" {text.lower()} "
    if not any(t in lower for t in _TICKETING_TERMS):
        return False
    if any(t in lower for t in _TRAIN_TROUBLE_TERMS):
        return False
    return True

_sentiment_model  = None
_issue_type_model = None


def _load_models():
    global _sentiment_model, _issue_type_model
    if _sentiment_model is None:
        _sentiment_model = joblib.load(MODELS_DIR / "sentiment_baseline.joblib")
    if _issue_type_model is None:
        _issue_type_model = joblib.load(MODELS_DIR / "issue_type_baseline.joblib")


def _gemini_classify(text: str) -> dict | None:
    # The local model has already produced a prediction; Gemini only refines a
    # low-confidence one. Waiting out its timeout with no network buys nothing
    # and costs the caller ~8 s, so skip straight to the local answer.
    from agents.net_guard import is_offline, mark_offline, mark_online
    if is_offline():
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel("models/gemini-flash-lite-latest")

        prompt = f"""You are a transit disruption classifier for Rapid KL / KL LRT.
Classify the following social media post.

Rules:
- sentiment: must be exactly one of: negative, neutral, positive
- issue_type: must be exactly one of: breakdown, delay, crowding, aircond, staff_service, information, other

Text: "{text}"

Reply with ONLY valid JSON, no explanation:
{{"sentiment": "...", "issue_type": "..."}}"""

        # Hard timeout: the local prediction is already computed, so if Gemini
        # is slow we must fall back to it rather than hang the whole request.
        # (Live/ambiguous traffic escalates to this path often, so an uncapped
        # call here stalls /nlp/detect, /voice and the orchestrator.)
        response = model.generate_content(
            prompt, request_options={"timeout": 8})
        raw = response.text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())

        # Validate
        valid_sentiments  = {"negative", "neutral", "positive"}
        valid_issue_types = {"breakdown", "delay", "crowding", "aircond",
                             "staff_service", "information", "other"}
        if result.get("sentiment") not in valid_sentiments:
            return None
        if result.get("issue_type") not in valid_issue_types:
            return None

        return result
    except Exception as e:
        # A network-shaped failure trips the breaker so the rest of this
        # request (Supabase logging, live status) skips its own timeouts too.
        if isinstance(e, (OSError, TimeoutError)) or "deadline" in str(e).lower():
            mark_offline()
        print(f"[NLP] Gemini fallback failed: {e}")
        return None


# Explicit past-time markers (EN + BM). Deliberately conservative: only
# unambiguous phrases count, and any ongoing/recurring signal overrides them —
# "delayed since yesterday" and "rosak LAGI" are live events, "broke down last
# week" is a memory. False negatives are acceptable: a genuinely live event
# will attract other reports without past markers (corroboration covers it).
_PAST_MARKERS = (
    "last week", "last month", "last night", "yesterday", "the other day",
    "days ago", "weeks ago", "a month ago", "months ago",
    "minggu lepas", "bulan lepas", "malam tadi", "semalam", "kelmarin",
    "tempoh hari", "hari tu", "haritu",
)
_ONGOING_MARKERS = (
    "still", "since", "again", "now", "currently", "right now", "ongoing",
    "masih", "sejak", "lagi", "sekarang", "tengah", "sedang",
)


# Month-day dates ("On July 5", "5 Julai", "5hb Julai") — news reports about
# past incidents cite calendar dates rather than "last week" phrasing.
_MONTHS = {
    "jan": 1, "january": 1, "januari": 1, "feb": 2, "february": 2,
    "februari": 2, "mar": 3, "march": 3, "mac": 3, "apr": 4, "april": 4,
    "may": 5, "mei": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "julai": 7,
    "aug": 8, "august": 8, "ogos": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "oktober": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12, "disember": 12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DATE_RE = re.compile(
    rf"\b(?:({_MONTH_ALT})\.?\s+(\d{{1,2}})|(\d{{1,2}})(?:st|nd|rd|th|hb)?\s+({_MONTH_ALT}))\b")


def _mentions_old_date(text: str, now: datetime | None = None) -> bool:
    """True if the text cites an explicit month-day date more than 2 days in
    the past (nearest past occurrence when the year is unstated)."""
    now = now or datetime.now()
    for m in _DATE_RE.finditer(text.lower()):
        month_tok = m.group(1) or m.group(4)
        day_tok = m.group(2) or m.group(3)
        month, day = _MONTHS[month_tok], int(day_tok)
        try:
            cited = datetime(now.year, month, day)
        except ValueError:
            continue                      # e.g. "Feb 30" — not a real date
        if cited > now + timedelta(days=1):
            cited = cited.replace(year=now.year - 1)   # "July 5" said in March
        if (now - cited) > timedelta(days=2):
            return True
    return False


def _refers_to_past(text: str) -> bool:
    """True when the text explicitly places the event in the past AND gives
    no signal that the problem is still ongoing. Past placement is either a
    past-time phrase ("last week", "semalam") or an explicit calendar date
    more than 2 days old ("On July 5" in a news recap)."""
    lower = f" {text.lower()} "
    has_past = any(m in lower for m in _PAST_MARKERS) or _mentions_old_date(text)
    if not has_past:
        return False
    has_ongoing = any(f" {m} " in lower or lower.rstrip().endswith(f" {m}")
                      for m in _ONGOING_MARKERS)
    return not has_ongoing


def predict(text: str, allow_remote: bool = True) -> dict:
    _load_models()
    sentiment  = _sentiment_model.predict([text])[0]
    issue_type = _issue_type_model.predict([text])[0]
    sent_proba   = _sentiment_model.predict_proba([text])[0]
    sent_classes = list(_sentiment_model.classes_)
    sentiment_scores = {
        cls: round(float(p) * 100, 1)
        for cls, p in zip(sent_classes, sent_proba)
    }
    issue_proba   = _issue_type_model.predict_proba([text])[0]
    issue_classes = list(_issue_type_model.classes_)
    issue_scores = {
        cls: round(float(p) * 100, 1)
        for cls, p in zip(issue_classes, issue_proba)
    }
    top_sent_conf  = max(sentiment_scores.values())
    top_issue_conf = max(issue_scores.values())
    method = "local"

    if allow_remote and (top_sent_conf < SENT_THRESHOLD
                         or top_issue_conf < ISSUE_THRESHOLD):
        gemini = _gemini_classify(text)
        if gemini:
            sentiment  = gemini["sentiment"]
            issue_type = gemini["issue_type"]
            method = "gemini_fallback"
            print(f"[NLP] Gemini fallback used (sent_conf={top_sent_conf:.0f}%, issue_conf={top_issue_conf:.0f}%)")

    # Ticketing/equipment outages (token machines, counters) are not
    # train-service breakdowns — downgrade so the alert rule cannot fire.
    if issue_type in ("breakdown", "delay") and _is_ticketing_only(text):
        issue_type = "information"

    disruption_alert = (
        sentiment == "negative" and issue_type in ("breakdown", "delay")
    )

    # A complaint about a PAST event ("train broke down last week") is a
    # complaint, not a live alert — explicit past-time references suppress the
    # alert flag unless the text also signals the problem is ongoing.
    past_reference = _refers_to_past(text)
    if disruption_alert and past_reference:
        disruption_alert = False

    return {
        "sentiment":        sentiment,
        "issue_type":       issue_type,
        "disruption_alert": disruption_alert,
        "past_reference":   past_reference,
        "sentiment_scores": sentiment_scores,
        "issue_scores":     issue_scores,
        "method":           method,
        "input_text":       text,
    }
