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
