"""
Intent gate tests — does a scraped post report a live service problem?

The gate exists because the classifier cannot tell a commuter stuck on a
platform from someone using a breakdown as a punchline, and both were raising
alerts that fed corroboration. These tests pin the three properties that make
it safe to turn on: it is OFF by default, it FAILS OPEN, and it never second-
guesses an official announcement.

Fully offline — both providers are blocked by a conftest fixture, and the
tests that need a verdict supply one.
"""
import pytest

import agents.intent_gate as gate


def _verdict(live, why="because"):
    """A provider that replies with a well-formed JSON verdict."""
    import json
    return lambda prompt, timeout=None: json.dumps({"live": live, "why": why})


# ── off by default ───────────────────────────────────────────────────────────

def test_gate_is_off_by_default():
    """It adds a network call to the ingestion path and changes how much
    evidence a confirmation needs. Neither may happen on an import."""
    assert gate.INTENT_GATE is False


def test_disabled_gate_makes_no_call_and_keeps_every_alert(monkeypatch):
    called = []
    monkeypatch.setattr(gate, "_call_gemini",
                        lambda p, t=None: called.append(p) or '{"live": false}')
    out = gate.filter_alert("lrt kj rosak sebab loke letak jawatan ke")
    assert out["alert"] is True
    assert out["checked_by"] is None
    assert called == []


# ── the decision itself ──────────────────────────────────────────────────────

def test_live_report_keeps_its_alert(monkeypatch):
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "_call_gemini", _verdict(True, "stuck on platform"))
    out = gate.filter_alert("stuck at masjid jamek 30 mins, no train coming")
    assert out["alert"] is True
    assert out["checked_by"] == "gemini"


def test_commentary_loses_its_alert(monkeypatch):
    """The real logged post that motivated this: a political joke naming a
    Rapid KL line, which contributed 0.4 corroboration weight."""
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "_call_gemini", _verdict(False, "political joke"))
    out = gate.filter_alert("lrt kj rosak sebab loke letak jawatan ke")
    assert out["alert"] is False
    assert out["why"] == "political joke"
    assert out["checked_by"] == "gemini"


def test_official_announcements_are_never_gated(monkeypatch):
    """@AskRapidKL is authoritative. There is nothing to second-guess, and a
    gate that could veto an official alert would be a new failure mode."""
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    called = []
    monkeypatch.setattr(gate, "_call_gemini",
                        lambda p, t=None: called.append(p) or '{"live": false}')
    out = gate.filter_alert("Perkhidmatan Laluan Kelana Jaya terganggu",
                            official=True)
    assert out["alert"] is True
    assert called == []                 # and it does not even cost a call


# ── fails open ───────────────────────────────────────────────────────────────

def test_provider_outage_keeps_the_alert(monkeypatch):
    """Under-reporting a real disruption is worse than counting a joke, so
    every uncertain case resolves towards keeping the signal."""
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    out = gate.filter_alert("kelana jaya line down at kampung baru")
    assert out["alert"] is True         # both providers blocked by conftest
    assert out["checked_by"] is None    # ...and the caller can tell


def test_unparseable_reply_keeps_the_alert(monkeypatch):
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "_call_gemini", lambda p, t=None: "probably not a real one")
    out = gate.filter_alert("kelana jaya line down")
    assert out["alert"] is True
    assert out["checked_by"] is None


def test_non_boolean_verdict_is_not_an_answer(monkeypatch):
    """'maybe' is not a decision. Treat it as no verdict rather than guessing
    which way the model was leaning."""
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "_call_gemini", lambda p, t=None: '{"live": "maybe"}')
    out = gate.filter_alert("kelana jaya line down")
    assert out["alert"] is True
    assert out["checked_by"] is None


def test_empty_post_is_kept_without_a_call(monkeypatch):
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    called = []
    monkeypatch.setattr(gate, "_call_gemini",
                        lambda p, t=None: called.append(p) or '{"live": false}')
    assert gate.filter_alert("   ")["alert"] is True
    assert called == []


# ── provider fallback ────────────────────────────────────────────────────────

def test_falls_through_to_the_second_provider(monkeypatch):
    """A verdict from either provider is worth more than no verdict."""
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "GATE_PROVIDER", "gemini")
    monkeypatch.setattr(gate, "_call_groq", _verdict(False, "news summary"))
    out = gate.filter_alert("LRT3 delayed, contractor kecil angry, loses power")
    assert out["alert"] is False
    assert out["checked_by"] == "groq"   # gemini is blocked; groq answered


def test_configured_provider_is_tried_first(monkeypatch):
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "GATE_PROVIDER", "groq")
    order = []
    monkeypatch.setattr(gate, "_call_gemini",
                        lambda p, t=None: order.append("gemini") or '{"live": true}')
    monkeypatch.setattr(gate, "_call_groq",
                        lambda p, t=None: order.append("groq") or '{"live": true}')
    gate.filter_alert("train stuck at kampung baru")
    assert order == ["groq"]             # answered first time, no fallthrough


def test_markdown_fenced_json_is_still_read(monkeypatch):
    """Gemini wraps JSON in a fence often enough that stripping it is not
    optional — without this the gate would fail open on every call."""
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "_call_gemini",
                        lambda p, t=None: '```json\n{"live": false, "why": "meme"}\n```')
    out = gate.filter_alert("i pejuang lrt kelana jaya line")
    assert out["alert"] is False
    assert out["checked_by"] == "gemini"


# ── the prompt has to carry the cases it is judged on ────────────────────────

def test_prompt_names_the_klang_valley_lines(monkeypatch):
    """A gate that does not know which network it is filtering for cannot
    reject a Jakarta post, which is one of the categories it is meant to."""
    captured = []
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "_call_gemini",
                        lambda p, t=None: captured.append(p) or '{"live": true}')
    gate.filter_alert("mrt rosak")
    prompt = captured[0]
    for line in ("Kelana Jaya", "Ampang", "LRT3", "Kajang", "Putrajaya",
                 "Monorail", "Komuter"):
        assert line in prompt
    assert "mrt rosak" in prompt


def test_long_posts_are_truncated_before_sending(monkeypatch):
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    captured = []
    monkeypatch.setattr(gate, "_call_gemini",
                        lambda p, t=None: captured.append(p) or '{"live": true}')
    gate.filter_alert("x" * 5000)
    assert captured[0].count("x") <= 1100      # 1000 of post + prompt's own


# ── what the gate does NOT filter, documented rather than hidden ─────────────

def test_a_hoax_that_describes_an_emergency_is_kept(monkeypatch):
    """The real Bukit Jalil pair was 'go to taipan from bukit jalil' and 'got
    bomb at lrt bukit jalil'. The gate clears the first and KEEPS the second,
    and that is the right call on its own terms: a bomb at a station IS a live
    service problem if true, and a filter that suppressed a reported emergency
    would be the worse failure. The gate judges intent, not truth.

    Clearing one of the two is enough to drop that confirmation below the
    threshold — which is what the replay measured — but the residual stands:
    a hoax at weight 1.0 plus one more in-app report still confirms. Only
    per-user weighting closes that, and the system stores no identifier.
    """
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "_call_gemini",
                        lambda p, t=None: '{"live": true, "why": "reports emergency at station"}')
    assert gate.filter_alert("got bomb at lrt bukit jalil")["alert"] is True
