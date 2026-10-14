from agents.nlp_agent import predict


def test_output_contract():
    r = predict("LRT Kelana Jaya breakdown at KLCC, stuck 40 minutes!")
    for key in ("sentiment", "issue_type", "disruption_alert",
                "sentiment_scores", "issue_scores", "method"):
        assert key in r
    assert r["method"] == "local"          # Gemini blocked by conftest
    assert abs(sum(r["sentiment_scores"].values()) - 100) < 1.5
    assert abs(sum(r["issue_scores"].values()) - 100) < 1.5


def test_alert_rule_is_breakdown_or_delay_and_negative():
    # Contract test, not a prediction snapshot: alert iff negative AND breakdown/delay
    r = predict("Train broke down again at Masjid Jamek, so angry, terrible service")
    expected = r["sentiment"] == "negative" and r["issue_type"] in ("breakdown", "delay")
    assert r["disruption_alert"] is expected


def test_positive_text_no_alert():
    r = predict("Service running smooth today, love the new trains!")
    assert r["disruption_alert"] is False


def test_survives_short_and_mixed_language_input():
    for text in ("lrt rosak", "ok je", "aircond sejuk gila best"):
        r = predict(text)
        assert r["sentiment"] in ("negative", "neutral", "positive")


# ── Past-reference guard: memories are complaints, not live alerts ───────────

from agents.nlp_agent import _refers_to_past, predict


def test_past_complaint_suppresses_alert():
    r = predict("the KJ train broke down last week at Wangsa Maju, so frustrating")
    assert r["past_reference"] is True
    assert r["disruption_alert"] is False       # logged as complaint, no alert


def test_ongoing_marker_overrides_past_marker():
    # "since yesterday" = still happening → alert must survive
    assert _refers_to_past("LRT delayed since yesterday and STILL not fixed") is False
    # "rosak lagi" = broken AGAIN (recurring now) → live
    assert _refers_to_past("tren rosak lagi kat kampung baru") is False


def test_malay_past_marker():
    assert _refers_to_past("lrt rosak minggu lepas kat sungai besi") is True
    assert _refers_to_past("tren tergendala semalam") is True


def test_present_report_unaffected():
    r = predict("Kelana Jaya line completely broken down at KLCC, trains not moving!")
    assert r["past_reference"] is False
    assert r["disruption_alert"] is True


def test_dated_news_report_is_not_a_live_alert():
    """A news tweet citing an explicit past date (the @dajiyuan LRT3 recap)
    must classify as a complaint/report, never a live alert."""
    from datetime import datetime, timedelta
    from agents.nlp_agent import _mentions_old_date

    text = ("Malaysia's China-Made Trains Experience Failure in First Week of "
            "Operation. On July 5, Kuala Lumpur Rapid KL-operated Shah Alam "
            "Light Rail Transit Line 3 (LRT3) encountered a train accident. "
            "The train suddenly stopped")
    now = datetime(2026, 7, 12)
    assert _mentions_old_date(text, now=now) is True

    # date only 1 day old → still treated as current (conservative)
    assert _mentions_old_date("breakdown on July 11 at KLCC", now=now) is False
    # unstated year: "July 5" said in March refers to LAST July → past
    assert _mentions_old_date("accident on July 5", now=datetime(2026, 3, 1)) is True
    # Malay date form
    assert _mentions_old_date("tren rosak pada 5hb Julai", now=now) is True
    # no date, no past phrase → unaffected
    assert _mentions_old_date("train stuck at KLCC right now", now=now) is False


def test_dated_news_report_suppresses_alert_end_to_end():
    from datetime import datetime, timedelta
    old = (datetime.now() - timedelta(days=10)).strftime("%B ") + \
          str((datetime.now() - timedelta(days=10)).day)
    r = predict(f"On {old}, the LRT3 train broke down at Stadium Shah Alam "
                "and passengers were stranded")
    assert r["past_reference"] is True
    assert r["disruption_alert"] is False


# ── Ticketing / equipment guard ──────────────────────────────────────────────
# A token-machine / counter outage is NOT a train-service breakdown. Left
# unguarded, an OFFICIAL such post confirms a line instantly and falsely cuts
# it from routing while trains run normally.

_OTP_POST = (
    "Kajang Line: there is a communication disruption affecting the Office "
    "Ticket Processor (OTP) system at several stations. Consequently, the OTP "
    "machines at the counters are temporarily out of service and unable to "
    "issue tokens."
)


def test_is_ticketing_only_true_for_otp_outage():
    from agents.nlp_agent import _is_ticketing_only
    assert _is_ticketing_only(_OTP_POST) is True


def test_is_ticketing_only_stands_down_when_trains_affected():
    from agents.nlp_agent import _is_ticketing_only
    # mentions a token, but the trains themselves are the problem → keep label
    assert _is_ticketing_only("train broke down, everyone stuck, no tokens") is False


def test_is_ticketing_only_false_for_plain_breakdown():
    from agents.nlp_agent import _is_ticketing_only
    assert _is_ticketing_only("Kelana Jaya line broken down at KLCC") is False


def test_official_otp_outage_does_not_raise_disruption_alert():
    """The OTP/token-machine outage must never trip the disruption alert —
    a single official post would otherwise falsely mark the line disrupted."""
    r = predict(_OTP_POST)
    assert r["disruption_alert"] is False


# ── Intent gate on the in-app report path ────────────────────────────────────
# This is the path where the gate earns its place. Replaying the real log
# showed the single false confirmation in the data was built from two IN-APP
# reports nine minutes apart — "go to taipan from bukit jalil" (a navigation
# request) and "got bomb at lrt bukit jalil" (a prank). At weight 1.0 each
# that reached the 2.0 threshold and would have cut Bukit Jalil out of
# everyone's routing.

import api.nlp as nlp_api
from api.nlp import NLPRequest, detect


def _force_alert(monkeypatch, text="train broke down at bukit jalil"):
    monkeypatch.setattr(nlp_api, "predict", lambda t: {
        "sentiment": "negative", "issue_type": "breakdown",
        "disruption_alert": True, "method": "local",
        "sentiment_scores": {}, "issue_scores": {}})
    logged = []
    monkeypatch.setattr(nlp_api, "log_disruption",
                        lambda **kw: logged.append(kw))
    return logged


def test_navigation_request_is_logged_without_the_alert_flag(monkeypatch):
    import agents.intent_gate as gate
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "_call_gemini",
                        lambda p, t=None: '{"live": false, "why": "navigation request"}')
    logged = _force_alert(monkeypatch)

    out = detect(NLPRequest(text="go to taipan from bukit jalil"))
    (row,) = logged
    assert row["disruption_alert"] is False       # stops voting
    assert row["method"].endswith("+gate_filtered")
    assert out["disruption_alert"] is False       # ...and the caller is told
    assert out["gate_filtered"] is True


def test_a_real_report_is_unaffected(monkeypatch):
    import agents.intent_gate as gate
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "_call_gemini",
                        lambda p, t=None: '{"live": true, "why": "stuck now"}')
    logged = _force_alert(monkeypatch)

    out = detect(NLPRequest(text="train broke down at bukit jalil, stuck here"))
    assert logged[0]["disruption_alert"] is True
    assert out["disruption_alert"] is True
    assert "gate_filtered" not in out


def test_gate_outage_keeps_the_in_app_report(monkeypatch):
    """Fails open: both providers blocked by conftest."""
    import agents.intent_gate as gate
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    logged = _force_alert(monkeypatch)

    out = detect(NLPRequest(text="train broke down at bukit jalil"))
    assert logged[0]["disruption_alert"] is True
    assert out["disruption_alert"] is True


def test_disabled_gate_costs_no_call_on_this_path(monkeypatch):
    import agents.intent_gate as gate
    called = []
    monkeypatch.setattr(gate, "_call_gemini",
                        lambda p, t=None: called.append(p) or '{"live": false}')
    logged = _force_alert(monkeypatch)

    detect(NLPRequest(text="train broke down at bukit jalil"))
    assert logged[0]["disruption_alert"] is True
    assert called == []


def test_non_alert_reports_never_reach_the_gate(monkeypatch):
    """Most submissions are not alerts. Spending a model call on them would
    make every report cost one for no decision."""
    import agents.intent_gate as gate
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    called = []
    monkeypatch.setattr(gate, "_call_gemini",
                        lambda p, t=None: called.append(p) or '{"live": false}')
    monkeypatch.setattr(nlp_api, "predict", lambda t: {
        "sentiment": "neutral", "issue_type": "information",
        "disruption_alert": False, "method": "local",
        "sentiment_scores": {}, "issue_scores": {}})
    monkeypatch.setattr(nlp_api, "log_disruption", lambda **kw: None)

    detect(NLPRequest(text="what time does the lrt open"))
    assert called == []
