"""
Transcription backend selection — which engine serves a request, and what the
process loads at startup. Fully offline: no model is ever constructed here.
"""
import agents.transcribe_agent as ta


# ── Startup warm-up must match the backend that will serve requests ─────────
# warm() used to load the local model unconditionally. Harmless on an always-on
# host with a GPU, wrong everywhere else: the deployed backend sets
# WHISPER_BACKEND=groq, so local is only a fallback, yet every start paged in a
# ~1.5 GB large-v3 download from HuggingFace that no request would ever use. On
# a container that sleeps after idle that is a 1.5 GB download on every wake,
# competing for the memory and disk of a 512 MB instance and adding to a cold
# start the user is already being asked to wait through.

def test_warm_skips_the_local_model_when_groq_serves_requests(monkeypatch):
    loaded = []
    monkeypatch.setattr(ta, "_get_model", lambda: loaded.append(1))
    monkeypatch.setattr(ta, "BACKEND", "groq")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "key")
    ta.warm()
    assert loaded == []


def test_warm_loads_when_local_is_the_only_backend(monkeypatch):
    loaded = []
    monkeypatch.setattr(ta, "_get_model", lambda: loaded.append(1))
    monkeypatch.setattr(ta, "BACKEND", "auto")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "")
    ta.warm()
    assert loaded == [1]


def test_warm_loads_when_local_is_explicitly_chosen(monkeypatch):
    """WHISPER_BACKEND=local is a deliberate choice — an offline demo or a
    privacy requirement — and must still pre-load."""
    loaded = []
    monkeypatch.setattr(ta, "_get_model", lambda: loaded.append(1))
    monkeypatch.setattr(ta, "BACKEND", "local")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "key")
    ta.warm()
    assert loaded == [1]


def test_the_fallback_still_loads_on_demand(monkeypatch):
    """Skipping the warm must not disable local transcription — it only moves
    the cost to the one request that needs it."""
    loaded = []
    monkeypatch.setattr(ta, "_get_model", lambda: loaded.append(1) or "model")
    monkeypatch.setattr(ta, "BACKEND", "groq")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "key")
    ta.warm()
    assert loaded == []
    assert ta._get_model() == "model"      # a request still pages it in


# ── Backend order ───────────────────────────────────────────────────────────

def test_local_backend_never_reaches_groq(monkeypatch):
    """The privacy/offline setting must not silently send audio to a third
    party because a key happens to be present."""
    monkeypatch.setattr(ta, "BACKEND", "local")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "key")
    assert ta._backend_order() == ["local"]


def test_groq_without_a_key_falls_back_to_local(monkeypatch):
    monkeypatch.setattr(ta, "BACKEND", "groq")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "")
    assert ta._backend_order() == ["local"]


def test_availability_does_not_trigger_a_cold_load(monkeypatch):
    """available() is polled by the frontend before recording, so it must not
    pay the ~30 s Whisper load."""
    loaded = []
    monkeypatch.setattr(ta, "_get_model", lambda: loaded.append(1))
    monkeypatch.setattr(ta, "BACKEND", "auto")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "")
    monkeypatch.setattr(ta, "_model", None)
    assert ta.available() is False         # nothing loaded yet, honestly false
    assert loaded == []
