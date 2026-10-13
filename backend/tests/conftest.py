"""
Shared fixtures. Hard rule: the suite must run GREEN with no network access —
every external call (Gemini, Supabase, Nominatim/Photon geocoding) is blocked.
"""
import pytest


@pytest.fixture(autouse=True)
def no_gemini(monkeypatch):
    """Block LLM fallback in every test — classification stays local."""
    import agents.nlp_agent as nlp
    monkeypatch.setattr(nlp, "_gemini_classify", lambda text: None)


@pytest.fixture(autouse=True)
def no_supabase_logging(monkeypatch):
    """api/nlp.py and api/voice.py bind log_disruption into their own
    namespaces at import — patch those bindings, not db.supabase_client."""
    import api.nlp as nlp_api
    import api.voice as voice_api
    monkeypatch.setattr(nlp_api, "log_disruption", lambda *a, **k: None)
    monkeypatch.setattr(voice_api, "log_disruption", lambda *a, **k: None)
    # voice assist also reads live line-status; keep it offline + empty
    monkeypatch.setattr(voice_api, "get_line_status",
                        lambda: {"disrupted_stations": []})


@pytest.fixture(autouse=True)
def no_rag_generation(monkeypatch):
    """Voice assist hands non-routing questions to rag_agent.answer (late
    import) — stub it to an empty answer so tests stay offline; individual
    tests override with a real stub. api/rag.py's own binding is untouched."""
    import agents.rag_agent as rag
    monkeypatch.setattr(rag, "answer",
                        lambda q, top_k=4, history=None: {"answer": "", "mode": "stub"})


@pytest.fixture(autouse=True)
def no_geocoding(monkeypatch):
    """Block Nominatim/Photon so failed station lookups fail fast + offline."""
    import agents.rerouting_agent as ra
    monkeypatch.setattr(ra, "_geocode_place", lambda q: None)


@pytest.fixture(autouse=True)
def no_intent_gate_calls(monkeypatch):
    """The ingestion intent gate asks a hosted model one question per alert.
    Block both providers so nothing in the suite can reach the network: an
    unpatched gate then fails open, which is the behaviour it promises anyway.
    Tests that exercise the gate monkeypatch over these."""
    import agents.intent_gate as gate
    def blocked(prompt):
        raise RuntimeError("network blocked in tests")
    monkeypatch.setattr(gate, "_call_gemini", blocked)
    monkeypatch.setattr(gate, "_call_groq", blocked)
