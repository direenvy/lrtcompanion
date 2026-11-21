"""
Grounding-verification tests — fully offline: both Gemini calls (generation
and verification) are replaced with fakes.

The generation prompt ASKS the model to answer only from retrieved context;
_verify_grounded CHECKS that it did. These tests cover the wiring. Whether the
checker is any good is a separate question — see scripts/verify_grounding_eval.py,
which feeds it deliberately wrong answers.
"""
import json

import pytest

import agents.rag_agent as ra

# conftest has an autouse fixture that stubs rag_agent.answer for the voice
# tests. Grab the real one at import, before any fixture runs, and restore it.
_REAL_ANSWER = ra.answer


CHUNKS = [
    {"text": "The My50 monthly pass costs RM50 and is valid for 30 days on all "
             "Rapid KL rail and bus services.", "source_file": "my50_faq.pdf"},
    {"text": "Passes are sold at any Rapid KL customer service counter.",
     "source_file": "my50_faq.pdf"},
]


class _Resp:
    def __init__(self, text): self.text = text


def _fake_model(reply):
    """A GenerativeModel stand-in whose generate_content returns `reply`."""
    class M:
        def __init__(self, *a, **k): pass
        def generate_content(self, prompt, request_options=None):
            if callable(reply):
                return _Resp(reply(prompt))
            return _Resp(reply)
    return M


@pytest.fixture
def no_network(monkeypatch):
    """Never configure a real client in tests."""
    monkeypatch.setattr(ra.genai, "configure", lambda **kw: None)


# ── the checker itself ───────────────────────────────────────────────────────

def test_supported_verdict_is_passed_through(no_network, monkeypatch):
    monkeypatch.setattr(ra.genai, "GenerativeModel",
                        _fake_model('{"verdict":"supported","unsupported":null}'))
    out = ra._verify_grounded("The My50 pass costs RM50.", CHUNKS)
    assert out["verdict"] == "supported" and out["unsupported"] is None


def test_unsupported_verdict_reports_the_offending_sentence(no_network, monkeypatch):
    monkeypatch.setattr(ra.genai, "GenerativeModel", _fake_model(
        '{"verdict":"unsupported","unsupported":"The My50 pass costs RM80."}'))
    out = ra._verify_grounded("The My50 pass costs RM80.", CHUNKS)
    assert out["verdict"] == "unsupported"
    assert "RM80" in out["unsupported"]


def test_markdown_fenced_json_is_parsed(no_network, monkeypatch):
    """Gemini often wraps JSON in a code fence; that must not read as a failure."""
    monkeypatch.setattr(ra.genai, "GenerativeModel", _fake_model(
        '```json\n{"verdict":"partial","unsupported":"Valid for 60 days."}\n```'))
    out = ra._verify_grounded("Costs RM50. Valid for 60 days.", CHUNKS)
    assert out["verdict"] == "partial"


def test_invalid_verdict_is_treated_as_unchecked(no_network, monkeypatch):
    """A creative verdict must not be trusted — only the three known values are."""
    monkeypatch.setattr(ra.genai, "GenerativeModel",
                        _fake_model('{"verdict":"mostly true","unsupported":null}'))
    assert ra._verify_grounded("anything", CHUNKS)["verdict"] == "unchecked"


def test_checker_failure_fails_open(no_network, monkeypatch):
    """A verifier outage must never become a refusal of service."""
    class Boom:
        def generate_content(self, prompt, request_options=None):
            raise TimeoutError("deadline exceeded")
    monkeypatch.setattr(ra.genai, "GenerativeModel", lambda *a, **k: Boom())
    monkeypatch.setattr(ra, "_verify_call_groq",
                        lambda p: (_ for _ in ()).throw(RuntimeError("no key")))
    out = ra._verify_grounded("The My50 pass costs RM50.", CHUNKS)
    assert out["verdict"] == "unchecked" and out["checked_by"] is None


def test_a_refusal_is_not_sent_for_checking(no_network, monkeypatch):
    """A refusal asserts nothing, so it needs no verification — and no API call."""
    calls = []
    class M:
        def generate_content(self, prompt, request_options=None):
            calls.append(prompt); return _Resp("{}")
    monkeypatch.setattr(ra.genai, "GenerativeModel", lambda *a, **k: M())
    out = ra._verify_grounded(ra.REFUSAL, CHUNKS)
    assert out["verdict"] == "supported"
    assert calls == []                       # the checker never ran


def test_empty_inputs_are_unchecked(no_network):
    assert ra._verify_grounded("", CHUNKS)["verdict"] == "unchecked"
    assert ra._verify_grounded("something", [])["verdict"] == "unchecked"


# ── the wiring inside answer() ───────────────────────────────────────────────

@pytest.fixture
def rag_env(monkeypatch, no_network):
    """answer() with retrieval and typo-correction stubbed, fares bypassed."""
    monkeypatch.setattr(ra, "_correct_terms", lambda q: (q, []))
    monkeypatch.setattr(ra.fare_lookup, "try_answer", lambda q: None)
    monkeypatch.setattr(ra, "_ensure_started", lambda: None)
    monkeypatch.setattr(ra, "_ready", True, raising=False)
    monkeypatch.setattr(ra, "_embedding_retrieve", lambda q, k: CHUNKS)
    

def _two_stage(generated, verdict):
    """Fake both calls: the first generates, the second returns `verdict`."""
    state = {"n": 0}
    def reply(prompt):
        state["n"] += 1
        return generated if state["n"] == 1 else json.dumps(
            {"verdict": verdict, "unsupported": None})
    return _fake_model(reply)


def test_unsupported_answer_is_replaced_by_the_refusal(rag_env, monkeypatch):
    monkeypatch.setattr(ra.genai, "GenerativeModel",
                        _two_stage("The My50 pass costs RM80.", "unsupported"))
    out = _REAL_ANSWER("How much is the My50 pass?")
    assert out["answer"] == ra.REFUSAL
    assert out["grounding"]["verdict"] == "unsupported"
    assert out["mode"].endswith("_refused_on_verify")


def test_supported_answer_survives_with_its_verdict(rag_env, monkeypatch):
    monkeypatch.setattr(ra.genai, "GenerativeModel",
                        _two_stage("The My50 pass costs **RM50**.", "supported"))
    out = _REAL_ANSWER("How much is the My50 pass?")
    assert "RM50" in out["answer"]
    assert out["grounding"]["verdict"] == "supported"
    assert "refused" not in out["mode"]


def test_partial_verdict_also_refuses(rag_env, monkeypatch):
    """A mostly-right answer is the dangerous kind — it reads as authoritative.

    The adversarial set showed the checker returns 'partial', not 'unsupported',
    for a right price with a wrong duration and for a plausible invented detail.
    Serving those would put an unverified number in front of someone about to
    act on it, so partial refuses too.
    """
    monkeypatch.setattr(ra.genai, "GenerativeModel",
                        _two_stage("Costs RM50. Valid for 60 days.", "partial"))
    out = _REAL_ANSWER("How much is the My50 pass?")
    assert out["answer"] == ra.REFUSAL
    assert out["grounding"]["verdict"] == "partial"
    assert out["mode"].endswith("_refused_on_verify")


def test_unchecked_verdict_still_serves_the_answer(rag_env, monkeypatch):
    """Fail-open at the wiring level, not just inside the checker: a verifier
    that could not run must not withhold an answer retrieval already produced."""
    monkeypatch.setattr(ra.genai, "GenerativeModel",
                        _two_stage("The My50 pass costs **RM50**.", "not-a-verdict"))
    out = _REAL_ANSWER("How much is the My50 pass?")
    assert "RM50" in out["answer"]
    assert out["grounding"]["verdict"] == "unchecked"
    assert "refused" not in out["mode"]


def test_fare_answers_skip_verification_entirely(monkeypatch, no_network):
    """The fare path involves no model, so it must not cost a second API call."""
    monkeypatch.setattr(ra, "_correct_terms", lambda q: (q, []))
    monkeypatch.setattr(ra.fare_lookup, "try_answer",
                        lambda q: "**KLCC to Ampang costs RM4.20 cash.**")
    called = []
    monkeypatch.setattr(ra, "_verify_grounded",
                        lambda a, c: called.append(1) or {"verdict": "supported"})
    out = _REAL_ANSWER("How much from KLCC to Ampang?")
    assert out["mode"] == "fare_lookup"
    assert called == []
    assert "grounding" not in out or out.get("grounding") is None


# ── two providers ────────────────────────────────────────────────────────────

def test_falls_back_to_the_other_provider(no_network, monkeypatch):
    """Gemini down must not mean unverified — Groq is asked instead.

    This is the point of having two: quota on one provider ran the first
    adversarial evaluation into the ground, and a verifier that dies with its
    model is a verifier you cannot rely on.
    """
    class Boom:
        def __init__(self, *a, **k): pass
        def generate_content(self, prompt, request_options=None):
            raise TimeoutError("deadline exceeded")
    monkeypatch.setattr(ra.genai, "GenerativeModel", Boom)
    monkeypatch.setattr(ra, "_verify_call_groq",
                        lambda p: '{"verdict":"unsupported","unsupported":"RM80"}')
    out = ra._verify_grounded("The My50 pass costs RM80.", CHUNKS)
    assert out["verdict"] == "unsupported"
    assert out["checked_by"] == "groq"


def test_the_verdict_records_which_model_judged_it(no_network, monkeypatch):
    """Without this the logs cannot tell a Gemini verdict from a Groq one, and
    comparing the two providers becomes impossible after the fact."""
    monkeypatch.setattr(ra.genai, "GenerativeModel",
                        _fake_model('{"verdict":"supported","unsupported":null}'))
    assert ra._verify_grounded("The My50 pass costs RM50.", CHUNKS)["checked_by"] == "gemini"


def test_an_unusable_verdict_tries_the_other_provider(no_network, monkeypatch):
    """A reply we cannot interpret is not a verdict — ask someone else before
    giving up and serving the answer unchecked."""
    monkeypatch.setattr(ra.genai, "GenerativeModel",
                        _fake_model('{"verdict":"mostly true","unsupported":null}'))
    monkeypatch.setattr(ra, "_verify_call_groq",
                        lambda p: '{"verdict":"partial","unsupported":"a detail"}')
    out = ra._verify_grounded("anything", CHUNKS)
    assert out["verdict"] == "partial" and out["checked_by"] == "groq"


# ── Degrading when the model is unavailable ─────────────────────────────────
# Found in production: an invalid Gemini key made the query-embedding call
# raise, nothing caught it, and /api/rag/chat returned HTTP 500 for every
# prose question. Generation was already guarded; embedding was not, and that
# asymmetry was invisible until the key died. Fare and network-fact questions
# kept working throughout, because they involve no model at all.

import agents.rag_agent as rag


def _no_model(monkeypatch):
    """Every model call fails, as an invalid or revoked key makes them."""
    def dead(*a, **k):
        raise RuntimeError("API key not valid")
    monkeypatch.setattr(rag.genai, "embed_content", dead)
    monkeypatch.setattr(rag.genai, "GenerativeModel", dead)


def test_a_dead_key_does_not_500_the_chatbot(monkeypatch):
    _no_model(monkeypatch)
    out = _REAL_ANSWER("What are the LRT operating hours?")
    assert out["mode"].startswith("keyword")
    assert out["answer"]


def test_failed_embedding_falls_back_to_keyword_not_an_exception(monkeypatch):
    monkeypatch.setattr(rag, "_ready", True)
    monkeypatch.setattr(rag, "_embedding_retrieve",
                        lambda q, k: (_ for _ in ()).throw(RuntimeError("no key")))
    _no_model(monkeypatch)
    out = _REAL_ANSWER("How do I claim a refund?")
    assert out["mode"].startswith("keyword")


def test_off_topic_questions_still_refuse_without_a_model(monkeypatch):
    """The refusal is normally prompt-enforced and then verified. With no model
    in the loop neither applies, so retrieval itself has to decline."""
    _no_model(monkeypatch)
    out = _REAL_ANSWER("What is the weather tomorrow?")
    assert "couldn't find this" in out["answer"]


def test_keyword_extractive_answers_say_they_are_unverified(monkeypatch):
    """No embedding to score the match and no model to notice the passage does
    not answer the question. Several lexical signals were measured and none
    separate off-topic from on-topic, so the reply must not present a quote as
    a verified answer."""
    _no_model(monkeypatch)
    out = _REAL_ANSWER("What are the LRT operating hours?")
    assert "not a verified answer" in out["answer"]


def test_the_caveat_is_not_bolted_onto_a_refusal(monkeypatch):
    """A refusal is already honest; prefixing it would be noise."""
    _no_model(monkeypatch)
    out = _REAL_ANSWER("What is the weather tomorrow?")
    assert "closest passage" not in out["answer"]


def test_deterministic_paths_are_untouched_by_a_dead_key(monkeypatch):
    """These are why the deployed chatbot answered anything at all while the
    key was invalid — no model is involved in either."""
    _no_model(monkeypatch)
    assert _REAL_ANSWER("is KLCC wheelchair accessible?")["mode"] == "network_facts"
    assert _REAL_ANSWER("How much from KLCC to Ampang?")["mode"] == "fare_lookup"


def test_a_wholly_irrelevant_chunk_set_is_not_returned():
    """_keyword_retrieve returning its top_k whatever they scored was the bug
    behind the irrelevant answers: an empty list is a valid, meaningful
    result."""
    rag._load_chunks()
    assert rag._keyword_retrieve("zzzqqq vvvxxx wwwyyy", 5) == []


_REAL_ANSWER = rag.answer     # captured before conftest's stub fixture runs
