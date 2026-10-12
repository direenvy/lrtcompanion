"""
Line-status corroboration tiers — one uncorroborated signal must never
declare a line disrupted (offline; Supabase faked).
"""
from datetime import datetime, timezone, timedelta
import api.dashboard as dash


class _FakeQuery:
    def __init__(self, rows): self._rows = rows
    def __getattr__(self, _name):
        return lambda *a, **k: self
    def execute(self):
        class R: data = self._rows; count = len(self._rows)
        return R()


def _status_with(rows, monkeypatch):
    class FakeSB:
        def table(self, name): return _FakeQuery(rows)
    monkeypatch.setattr(dash, "_get_client", lambda: FakeSB())
    return dash.get_line_status()


def _row(text, mins_ago=5, source="user"):
    ts = (datetime.now(timezone.utc) - timedelta(minutes=mins_ago)).isoformat()
    return {"id": 1, "text": text, "sentiment": "negative",
            "issue_type": "breakdown", "created_at": ts, "source": source}


def test_single_tweet_is_unconfirmed_not_disrupted(monkeypatch):
    # the CRRC case: one opinion tweet about LRT3 must not redden the line
    out = _status_with([_row("LRT3 trains are unreliable, do not gamble lives",
                             source="x_live")], monkeypatch)
    assert out["lines"]["SA"]["status"] == "unconfirmed"


def test_two_inapp_reports_confirm_disruption(monkeypatch):
    # two deliberate in-app reports (weight 1.0 each) = 2.0 -> confirmed
    out = _status_with([
        _row("kelana jaya line down at kampung baru"),
        _row("KJ line stuck, train not moving near kampung baru station"),
    ], monkeypatch)
    assert out["lines"]["KJ"]["status"] == "disrupted"


def test_single_political_tweet_stays_unconfirmed(monkeypatch):
    # the LGE/cost-cutting tweet: mentions 'LRT3 delayed' politically, one
    # scraped tweet (weight 0.4) must never confirm a disruption
    out = _status_with([_row(
        "Dikecam MRT interchange cancelled, LRT3 delayed, contractor kecil angry, loses power",
        source="x_live")], monkeypatch)
    assert out["lines"]["SA"]["status"] == "unconfirmed"


def test_two_tweets_still_not_enough(monkeypatch):
    # two distinct tweets = 0.8 weight, still below 2.0 -> not confirmed
    out = _status_with([
        _row("kelana jaya line down", source="x_live"),
        _row("kj line stuck again today", source="x_live"),
    ], monkeypatch)
    assert out["lines"]["KJ"]["status"] == "unconfirmed"


def test_five_tweets_confirm_disruption(monkeypatch):
    # ~5 distinct external tweets (5 * 0.4 = 2.0) reach the confirm threshold.
    # These must be genuinely different sentences: the earlier fixture numbered
    # one template 0..4, which near-duplicate dedup now correctly collapses to a
    # single signal. Five near-identical posts ARE spam, so the fixture was
    # wrong, not the rule.
    out = _status_with([
        _row("kelana jaya line delayed again this morning", source="x_live"),
        _row("why is KJ so packed today, waited three trains", source="x_live"),
        _row("tren KJ tergendala, ramai tunggu kat platform", source="x_live"),
        _row("another signalling fault on the kelana jaya route", source="x_live"),
        _row("KJ line crawling, forty minutes late to work", source="x_live"),
    ], monkeypatch)
    assert out["lines"]["KJ"]["status"] == "disrupted"


def test_duplicate_spam_counts_once(monkeypatch):
    same = "kelana jaya line totally down"
    out = _status_with([_row(same, source="x_live")] * 8, monkeypatch)
    assert out["lines"]["KJ"]["status"] == "unconfirmed"   # spam is one 0.4 signal


def test_old_alerts_decay_to_recovering(monkeypatch):
    out = _status_with([_row("kelana jaya line down", mins_ago=90),
                        _row("kj line still broken", mins_ago=95)], monkeypatch)
    assert out["lines"]["KJ"]["status"] == "recovering"


def test_station_corroboration_still_split(monkeypatch):
    out = _status_with([_row("train stuck at kampung baru")], monkeypatch)
    assert out["disrupted_stations"] == []
    assert out["advisory_stations"][0]["name"] == "KAMPUNG BARU"


def test_single_official_announcement_confirms_instantly(monkeypatch):
    # one authoritative @AskRapidKL post (source x_official) confirms alone
    out = _status_with([_row(
        "Perkhidmatan Laluan Kelana Jaya terganggu, sila gunakan bas gantian",
        source="x_official")], monkeypatch)
    assert out["lines"]["KJ"]["status"] == "disrupted"


def test_source_weight_hierarchy():
    from api.dashboard import _source_weight, CONFIRM_WEIGHT
    assert _source_weight("x_official") >= CONFIRM_WEIGHT   # official confirms alone
    assert _source_weight("user") == 1.0                    # two in-app confirm
    assert _source_weight("voice") == 1.0
    assert _source_weight("x_live") < 1.0                   # several tweets needed


# ── near-duplicate deduplication ─────────────────────────────────────────────
# Exact-match dedup meant one person could reword a claim and earn a second
# helping of corroboration weight. Similarity matching raises that floor — but
# only for reports that reuse vocabulary, which these tests pin precisely so
# nobody later mistakes it for a complete defence.

def test_reordered_wording_counts_once(monkeypatch):
    """Same words, different order — one report, not two. Under exact-match
    dedup this pair reached CONFIRM_WEIGHT on its own."""
    out = _status_with([
        _row("stuck at kampung baru for 30 minutes, no announcement"),
        _row("no announcement, been stuck at kampung baru 30 minutes"),
    ], monkeypatch)
    assert out["lines"]["KJ"]["status"] == "unconfirmed"


def test_malay_reordering_counts_once(monkeypatch):
    """The guard must work on Malay reports too, not just English."""
    out = _status_with([
        _row("LRT rosak kat kampung baru, semua terkandas"),
        _row("kampung baru LRT rosak, orang ramai terkandas"),
    ], monkeypatch)
    assert out["lines"]["KJ"]["status"] == "unconfirmed"


def test_genuinely_different_reports_still_corroborate(monkeypatch):
    """The cost of merging must not be paid by real witnesses: two people
    describing the same event differently must still confirm it."""
    out = _status_with([
        _row("kelana jaya line down at kampung baru"),
        _row("KJ line stuck, train not moving near kampung baru station"),
    ], monkeypatch)
    assert out["lines"]["KJ"]["status"] == "disrupted"


def test_distinct_complaints_at_one_station_are_not_merged(monkeypatch):
    """Two different problems at the same station are two signals, not one."""
    out = _status_with([
        _row("train broke down at kampung baru, everyone is stuck on the platform"),
        _row("kampung baru escalator not working again, had to take the stairs"),
    ], monkeypatch)
    assert out["lines"]["KJ"]["status"] == "disrupted"


def test_similarity_dedup_does_not_defeat_a_varied_attacker(monkeypatch):
    """Documents the limit rather than hiding it.

    These two sentences describe one event and share almost no vocabulary —
    they score 54, below any threshold that keeps genuinely distinct reports
    apart. Lexical similarity cannot merge them, so one person writing both
    still reaches CONFIRM_WEIGHT. Only per-user weighting closes this, and the
    system stores no identifier by design. If this test ever starts failing,
    something has begun merging reports it should not.
    """
    out = _status_with([
        _row("train broke down at kampung baru, everyone is stuck on the platform"),
        _row("kampung baru LRT breakdown, service completely stopped"),
    ], monkeypatch)
    assert out["lines"]["KJ"]["status"] == "disrupted"


# ── semantic deduplication (opt-in) ──────────────────────────────────────────

def test_semantic_dedup_is_off_by_default(monkeypatch):
    """It must stay off unless asked for: it costs an embedding call on a hot
    path, and it changes how much evidence a confirmation needs."""
    assert dash.SEMANTIC_DEDUP is False
    called = []
    monkeypatch.setattr(dash, "_embed_report", lambda t: called.append(t) or None)
    _status_with([_row("kampung baru lrt down"),
                  _row("kampung baru lrt not working")], monkeypatch)
    assert called == []


def test_semantic_dedup_merges_what_tokens_cannot(monkeypatch):
    """The pair that motivated this: one event, two phrasings sharing almost no
    words. Lexically they score 54 and count twice; semantically 0.894."""
    monkeypatch.setattr(dash, "SEMANTIC_DEDUP", True)
    monkeypatch.setattr(dash, "_semantically_same",
                        lambda a, b: True)       # stand in for the real cosine
    out = _status_with([
        _row("train broke down at kampung baru, everyone is stuck on the platform"),
        _row("kampung baru LRT breakdown, service completely stopped"),
    ], monkeypatch)
    assert out["lines"]["KJ"]["status"] == "unconfirmed"


def test_semantic_dedup_falls_back_when_embeddings_are_down(monkeypatch):
    """An embedding outage must not take corroboration with it — the lexical
    rule still applies and the board keeps working."""
    monkeypatch.setattr(dash, "SEMANTIC_DEDUP", True)
    monkeypatch.setattr(dash, "_embed_report", lambda t: None)   # API unavailable
    out = _status_with([
        _row("kelana jaya line down at kampung baru"),
        _row("KJ line stuck, train not moving near kampung baru station"),
    ], monkeypatch)
    assert out["lines"]["KJ"]["status"] == "disrupted"


def test_lexical_match_short_circuits_before_any_embedding_call(monkeypatch):
    """Most duplicates are caught by tokens. Spending an embedding call on them
    would make the hot path cost far more than it needs to."""
    monkeypatch.setattr(dash, "SEMANTIC_DEDUP", True)
    called = []
    monkeypatch.setattr(dash, "_embed_report", lambda t: called.append(t) or None)
    _status_with([
        _row("stuck at kampung baru for 30 minutes, no announcement"),
        _row("no announcement, been stuck at kampung baru 30 minutes"),
    ], monkeypatch)
    assert called == []
