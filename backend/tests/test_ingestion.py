"""
Ingestion agent tests — fully offline: the X HTTP call, the NLP classifier,
and Supabase logging are all replaced with fakes (LIVE_DATA_PLAN B5).
"""
import urllib.error

import pytest

import agents.ingestion_agent as ia


FAKE_TWEETS = {
    "data": [
        {"id": "1001", "text": "LRT Kelana Jaya line breakdown at KLCC, stuck 20 minutes",
         "created_at": "2026-07-11T08:00:00.000Z"},
        {"id": "1002", "text": "Lovely quiet ride on the mrt this morning",
         "created_at": "2026-07-11T08:05:00.000Z"},
    ]
}


@pytest.fixture
def ingest_env(monkeypatch, tmp_path):
    """Token set, state isolated to tmp, X + NLP + Supabase all faked."""
    monkeypatch.setenv("X_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(ia, "STATE_PATH", tmp_path / "state.json")

    logged = []
    monkeypatch.setattr(ia, "log_disruption", lambda **kw: logged.append(kw))

    def fake_predict(text):
        is_alert = "breakdown" in text.lower()
        return {"sentiment": "negative" if is_alert else "positive",
                "issue_type": "service_disruption" if is_alert else "none",
                "disruption_alert": is_alert}
    monkeypatch.setattr(ia, "predict", fake_predict)

    monkeypatch.setattr(ia, "_sleep", lambda s: None)   # no real backoff in tests
    monkeypatch.setattr(ia, "_http_get_json", lambda url, headers: FAKE_TWEETS)
    monkeypatch.setattr(ia, "LABELLING_CSV", tmp_path / "live_x_labelling.csv")
    return logged


def test_pull_classifies_and_logs_alert_with_source_tag(ingest_env):
    logged = ingest_env
    summary = ia.run_pull()

    assert summary["status"] == "ok"
    assert summary["scanned"] == 2
    assert summary["alerts"] == 1          # only the breakdown tweet
    assert len(logged) == 1
    assert logged[0]["source"] == "x_live"
    assert logged[0]["created_at"] == "2026-07-11T08:00:00.000Z"
    assert logged[0]["disruption_alert"] is True


def test_pull_deduplicates_across_runs(ingest_env):
    logged = ingest_env
    ia.run_pull()
    summary2 = ia.run_pull()   # same fake tweets returned again

    assert summary2["scanned"] == 0        # nothing new classified
    assert summary2["alerts"] == 0
    assert len(logged) == 1                # alert not logged twice


def test_rate_limit_reported_not_raised(ingest_env, monkeypatch):
    def raise_429(url, headers):
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
    monkeypatch.setattr(ia, "_http_get_json", raise_429)

    summary = ia.run_pull()                # must not raise
    assert summary["status"] == "rate_limited"
    assert ia.get_status()["last_result"] == "rate_limited"


def test_x_error_reported_not_raised(ingest_env, monkeypatch):
    def raise_500(url, headers):
        raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)
    monkeypatch.setattr(ia, "_http_get_json", raise_500)

    summary = ia.run_pull()
    assert summary["status"] == "error"
    assert "500" in summary["detail"]


def test_transient_503_retries_then_succeeds(ingest_env, monkeypatch):
    calls = {"n": 0}

    def flaky(url, headers):
        calls["n"] += 1
        if calls["n"] < 3:                 # fail twice, succeed on the 3rd
            raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)
        return FAKE_TWEETS
    monkeypatch.setattr(ia, "_http_get_json", flaky)

    summary = ia.run_pull()
    assert summary["status"] == "ok"       # recovered within the same poll
    assert summary["scanned"] == 2
    assert calls["n"] == 3


def test_persistent_503_reported_after_retries(ingest_env, monkeypatch):
    calls = {"n": 0}

    def always_503(url, headers):
        calls["n"] += 1
        raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)
    monkeypatch.setattr(ia, "_http_get_json", always_503)

    summary = ia.run_pull()
    assert summary["status"] == "error"
    assert "503" in summary["detail"]
    assert calls["n"] == len(ia.RETRY_BACKOFF_SECONDS) + 1   # tried, then gave up


def test_missing_token_is_inactive_not_crash(monkeypatch, tmp_path):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    monkeypatch.setattr(ia, "STATE_PATH", tmp_path / "state.json")

    assert ia.start_polling() is False     # poller refuses to start
    summary = ia.run_pull()
    assert summary["status"] == "error"
    assert "not configured" in summary["detail"]
    assert ia.get_status()["configured"] is False


def test_status_counters_accumulate(ingest_env):
    ia.run_pull()
    status = ia.get_status()
    assert status["configured"] is True
    assert status["tweets_scanned"] == 2
    assert status["alerts_raised"] == 1
    assert status["last_result"] == "ok"
    assert status["last_poll"] is not None


def test_all_scanned_tweets_captured_for_labelling(ingest_env):
    """Part C raw material: every scanned tweet (alert or not) lands in the
    labelling CSV with its prediction and EMPTY human-label columns."""
    import csv as _csv
    ia.run_pull()
    with ia.LABELLING_CSV.open(encoding="utf-8") as f:
        rows = list(_csv.DictReader(f))
    assert len(rows) == 2                          # both tweets, not just the alert
    by_id = {r["id"]: r for r in rows}
    assert by_id["1001"]["disruption_alert"] == "True"
    assert by_id["1002"]["disruption_alert"] == "False"
    assert by_id["1001"]["pred_sentiment"] == "negative"
    assert all(r["sentiment"] == "" and r["issue_type"] == "" for r in rows)

    ia.run_pull()                                  # dedupe: no duplicate capture
    with ia.LABELLING_CSV.open(encoding="utf-8") as f:
        assert len(list(_csv.DictReader(f))) == 2


OFFICIAL_TWEETS = {
    "data": [
        {"id": "2001", "author_id": "9001",
         "text": "Service disruption on the Kelana Jaya Line due to a train "
                 "breakdown. Bridging buses are available.",
         "created_at": "2026-07-18T09:00:00.000Z"},
        {"id": "2002", "author_id": "9002",
         "text": "wah lrt breakdown again, KJ line stuck at KLCC",
         "created_at": "2026-07-18T09:02:00.000Z"},
    ],
    "includes": {"users": [
        {"id": "9001", "username": "AskRapidKL"},
        {"id": "9002", "username": "randomcommuter"},
    ]},
}


def test_official_account_tagged_x_official(ingest_env, monkeypatch):
    """An @AskRapidKL post is authoritative → source 'x_official';
    everyone else stays 'x_live'."""
    logged = ingest_env
    monkeypatch.setattr(ia, "_http_get_json", lambda url, headers: OFFICIAL_TWEETS)

    summary = ia.run_pull()
    assert summary["status"] == "ok" and summary["scanned"] == 2
    by_src = {row["source"] for row in logged}
    assert by_src == {"x_official", "x_live"}     # both alerts, different trust
    official = [r for r in logged if r["source"] == "x_official"]
    assert len(official) == 1
    assert "Kelana Jaya" in official[0]["text"]


def test_author_expansion_requested(ingest_env, monkeypatch):
    """The fetch must ask X for author usernames — without the expansion the
    official account cannot be recognised at all."""
    seen = {}

    def capture(url, headers):
        seen["url"] = url
        return OFFICIAL_TWEETS
    monkeypatch.setattr(ia, "_http_get_json", capture)

    ia.run_pull()
    assert "author_id" in seen["url"]        # expansions=author_id
    assert "username" in seen["url"]         # user.fields=username


# ── Stale since_id recovery ──────────────────────────────────────────────────
# X's recent-search window is 7 days. A cursor older than that is REJECTED with
# HTTP 400, not ignored, so without recovery the same dead id is resent on every
# poll and ingestion stalls permanently after any gap of over a week.

STALE_SINCE_ID_BODY = (
    b'{"detail":"One or more parameters to your request was invalid.",'
    b'"errors":[{"message":"\'since_id\' must be a tweet id created after '
    b'2026-10-05T10:18Z.","parameters":{"since_id":["2106294786084978930"]}}]}'
)


class _Body:
    """Minimal stand-in for the file-like object on an HTTPError."""
    def __init__(self, blob): self._blob = blob
    def read(self): return self._blob


def test_stale_since_id_clears_cursor_and_refetches(ingest_env, monkeypatch):
    """A 400 naming since_id drops the cursor and retries without it, in one poll."""
    ia._save_state({"seen_ids": [], "newest_id": "2106294786084978930",
                    "last_poll": None, "last_result": None,
                    "tweets_scanned": 0, "alerts_raised": 0})
    calls = []

    def stale_then_ok(url, headers):
        calls.append(url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                url, 400, "Bad Request", {}, _Body(STALE_SINCE_ID_BODY))
        return FAKE_TWEETS
    monkeypatch.setattr(ia, "_http_get_json", stale_then_ok)

    summary = ia.run_pull()
    assert summary["status"] == "ok" and summary["scanned"] == 2
    assert len(calls) == 2
    assert "since_id" in calls[0]            # first attempt sent the dead cursor
    assert "since_id" not in calls[1]        # retry dropped it
    assert ia._load_state()["newest_id"] == "1002"   # advanced to the newest post


def test_stale_cursor_cleared_even_when_the_retry_fails(ingest_env, monkeypatch):
    """The dead cursor must not survive a failed retry, or the next poll stalls too."""
    ia._save_state({"seen_ids": [], "newest_id": "2106294786084978930",
                    "last_poll": None, "last_result": None,
                    "tweets_scanned": 0, "alerts_raised": 0})

    def stale_then_down(url, headers):
        if "since_id" in url:
            raise urllib.error.HTTPError(
                url, 400, "Bad Request", {}, _Body(STALE_SINCE_ID_BODY))
        raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)
    monkeypatch.setattr(ia, "_http_get_json", stale_then_down)

    summary = ia.run_pull()
    assert summary["status"] == "error"          # reported, never raised
    assert ia._load_state()["newest_id"] is None  # cursor gone → next poll recovers


def test_other_400s_are_not_treated_as_a_stale_cursor(ingest_env, monkeypatch):
    """A malformed query is a real error — it must not silently drop the cursor."""
    ia._save_state({"seen_ids": [], "newest_id": "1500",
                    "last_poll": None, "last_result": None,
                    "tweets_scanned": 0, "alerts_raised": 0})

    def bad_query(url, headers):
        raise urllib.error.HTTPError(
            url, 400, "Bad Request", {},
            _Body(b'{"errors":[{"message":"Invalid query"}]}'))
    monkeypatch.setattr(ia, "_http_get_json", bad_query)

    summary = ia.run_pull()
    assert summary["status"] == "error"
    assert ia._load_state()["newest_id"] == "1500"   # cursor preserved


# ── intent gate wiring ───────────────────────────────────────────────────────
# The gate decides whether a classified alert keeps its disruption_alert flag.
# What matters here is that the post is still LOGGED either way: clearing the
# flag must stop it voting, not hide it from the feed.

def test_gated_post_is_logged_with_the_flag_cleared(ingest_env, monkeypatch):
    import agents.intent_gate as gate
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "_call_gemini", lambda p, t=None: '{"live": false, "why": "joke"}')

    summary = ia.run_pull()
    assert summary["alerts"] == 0 and summary["gated"] == 1
    (row,) = ingest_env                     # still one row written
    assert row["disruption_alert"] is False
    assert "breakdown" in row["text"].lower()
    assert row["method"].endswith("+gate_filtered")   # decision is auditable


def test_live_post_passes_the_gate_untouched(ingest_env, monkeypatch):
    import agents.intent_gate as gate
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "_call_gemini", lambda p, t=None: '{"live": true, "why": "stuck"}')

    summary = ia.run_pull()
    assert summary["alerts"] == 1 and summary["gated"] == 0
    (row,) = ingest_env
    assert row["disruption_alert"] is True
    assert "gate_filtered" not in (row["method"] or "")


def test_gate_outage_does_not_suppress_alerts(ingest_env, monkeypatch):
    """Both providers unavailable (conftest blocks them) — the alert stands."""
    import agents.intent_gate as gate
    monkeypatch.setattr(gate, "INTENT_GATE", True)

    summary = ia.run_pull()
    assert summary["alerts"] == 1 and summary["gated"] == 0
    assert ingest_env[0]["disruption_alert"] is True


def test_disabled_gate_leaves_ingestion_exactly_as_it_was(ingest_env):
    """The default path must be unchanged: no gate call, same alert count."""
    summary = ia.run_pull()
    assert summary["status"] == "ok"
    assert summary["scanned"] == 2 and summary["alerts"] == 1
    assert summary["gated"] == 0
    assert ingest_env[0]["disruption_alert"] is True


def test_gate_counters_are_reported_separately(ingest_env, monkeypatch):
    """A falling alert count could mean a quiet network or an eager gate.
    get_status has to distinguish them."""
    import agents.intent_gate as gate
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "_call_gemini", lambda p, t=None: '{"live": false, "why": "meme"}')

    ia.run_pull()
    status = ia.get_status()
    assert status["intent_gate"] is True
    assert status["alerts_gated"] == 1
    assert status["alerts_raised"] == 0
