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
    # ~5 distinct external tweets (5 * 0.4 = 2.0) reach the confirm threshold
    out = _status_with([
        _row(f"kelana jaya line problem number {i}", source="x_live")
        for i in range(5)
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
