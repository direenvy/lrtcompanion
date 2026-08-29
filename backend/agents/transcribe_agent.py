"""
Speech-to-text using a LOCAL Whisper model (faster-whisper / CTranslate2).

Why local rather than the browser's Web Speech API, which this replaces:

  * Web Speech ships audio to Google and therefore needs internet. A flaky demo
    network takes the whole voice feature down — the page already carries a
    "network" error string for exactly that failure.
  * It offers no way to supply a vocabulary. The spec's SpeechGrammarList is a
    no-op in Chrome, so "Kerinchi" competes against English priors and loses
    ("Karen chi", "Corinthian"). Whisper accepts `initial_prompt`, which biases
    decoding toward the station list — that single capability is the reason for
    the switch.

Measured on ten recordings of Malaysian station names (RTX 4050, large-v3,
int8_float16), scored by whether the routing pipeline resolved a full trip:

    Web Speech (Chrome)               ~3/10
    Whisper, no prompt                 6/10
    Whisper + station-name prompt      8/10     <- shipped
    Whisper + prompt + forced language 6/10

See scripts/whisper_vs_webspeech.py to reproduce.
"""
from __future__ import annotations

import os
import threading

# ── Backend selection ────────────────────────────────────────────────────────
# WHISPER_BACKEND controls which STT path is used first:
#   "local" — always faster-whisper on the local machine (needs a GPU to be fast)
#   "groq"  — always Groq's hosted whisper-large-v3, with local as fallback
#   "auto"  — pick "groq" if a Groq key is present, else "local"  (default)
#
# The deployed backend (Render — CPU only) sets WHISPER_BACKEND=groq. Locally
# nothing is set, so "auto" resolves to whichever the machine can actually run.
BACKEND      = os.getenv("WHISPER_BACKEND", "auto").lower()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")
GROQ_URL     = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_TIMEOUT = float(os.getenv("GROQ_TIMEOUT", "15"))

# ── Local-Whisper config ─────────────────────────────────────────────────────
# int8_float16 keeps large-v3 near 2 GB of VRAM, so it coexists with the rest
# of a demo machine (backend, browser, screen reader) on a 6 GB laptop card.
MODEL_SIZE   = os.getenv("WHISPER_MODEL", "large-v3")
DEVICE       = os.getenv("WHISPER_DEVICE", "cuda")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE", "int8_float16")

# Whisper reads at most ~224 tokens of initial_prompt and silently discards the
# rest, so the station list has to be chosen rather than dumped — all 171 names
# run to roughly 2,300 characters.
PROMPT_CHAR_BUDGET = 850

# Names that are ordinary English words already sit in Whisper's priors, and
# spending prompt budget on them crowds out the ones that actually get mangled.
_SAFE_IN_ENGLISH = {"university", "universiti", "central", "park", "garden",
                    "hospital", "airport", "terminal", "stadium", "museum"}

_model = None
_load_error: str | None = None
_lock = threading.Lock()


def _build_prompt() -> str:
    """Station-name vocabulary hint, ordered so the least guessable names
    survive the token budget."""
    try:
        from api.dashboard import _STATION_NAMES, _CONDITIONAL_STATION_NAMES
        names = {n.title() for n in [*_STATION_NAMES, *_CONDITIONAL_STATION_NAMES]
                 if len(n) > 3 and n.lower() not in _SAFE_IN_ENGLISH}
    except Exception:
        return ""

    def oddness(name: str) -> tuple:
        exotic = sum(ch in "kqxyz" for ch in name.lower())
        return (-exotic, -len(name.split()), name)

    prefix = "Kuala Lumpur rail stations: "
    out, used = [], len(prefix) + 1
    for n in sorted(names, key=oddness):
        if used + len(n) + 2 > PROMPT_CHAR_BUDGET:
            break
        out.append(n)
        used += len(n) + 2
    return prefix + ", ".join(out) + "."


_PROMPT: str | None = None


def prompt() -> str:
    global _PROMPT
    if _PROMPT is None:
        _PROMPT = _build_prompt()
    return _PROMPT


def _backend_order() -> list[str]:
    """Which backends to try, in priority order.

    WHISPER_BACKEND=local — never touch Groq (privacy or offline demo).
    WHISPER_BACKEND=groq  — Groq first, local as fallback (user picked "B").
    auto (default)         — Groq only when a key is present, else local only.
    """
    if BACKEND == "local":
        return ["local"]
    if BACKEND == "groq":
        return ["groq", "local"] if GROQ_API_KEY else ["local"]
    return ["groq", "local"] if GROQ_API_KEY else ["local"]


def available() -> bool:
    """True when at least one backend can serve a transcription.

    Deliberately CHEAP — this is polled by the frontend before recording, so it
    must not trigger the ~30 s Whisper cold load. Presence of the Groq key
    counts as "available" without a live probe; the local model reports its own
    load state via a previous call.
    """
    for b in _backend_order():
        if b == "groq" and GROQ_API_KEY:
            return True
        if b == "local":
            # Trust an already-loaded local model, but do NOT force a cold load
            # here (would block the /stt-status poll).
            if _model is not None:
                return True
    return False


def load_error() -> str | None:
    return _load_error


def _get_model():
    """Load once, lazily, under a lock. Weights are ~1.5 GB and take tens of
    seconds to page in, so this must not happen per request — and two requests
    arriving together must not both trigger it."""
    global _model, _load_error
    if _model is not None or _load_error is not None:
        return _model
    with _lock:
        if _model is not None or _load_error is not None:
            return _model
        try:
            from faster_whisper import WhisperModel
            _model = WhisperModel(MODEL_SIZE, device=DEVICE,
                                  compute_type=COMPUTE_TYPE)
            print(f"[Transcribe] Whisper {MODEL_SIZE} ready "
                  f"({DEVICE}/{COMPUTE_TYPE})")
        except Exception as e:
            # A missing GPU, missing package or absent weights must degrade to
            # the browser recogniser, never 500 the voice page.
            _load_error = str(e)
            print(f"[Transcribe] Whisper unavailable, browser speech will be "
                  f"used instead: {e}")
    return _model


def warm() -> None:
    """Load the model at startup so the first user does not pay for it."""
    _get_model()


# Languages a Klang Valley commuter plausibly speaks into this app. Auto-detect
# occasionally lands far outside this set — Thai and Chinese have both been
# observed on Malay speech — and a transcript in the wrong script cannot match
# any station, so the whole turn is lost. Detection is kept (it is what makes
# local names come out in Malay spelling, which the matcher recognises) but a
# wild result is retried against the language the user actually selected.
_PLAUSIBLE_LANGUAGES = {"en", "ms", "id"}


def _run_groq(audio_path: str, lang: str | None) -> tuple[str, str | None] | None:
    """One Groq transcription. Returns (text, detected_lang) or None on failure.

    Falls back rather than raising so the caller can try the next backend.
    verbose_json is requested so we get the detected language for the retry
    logic — plain "json" does not include it.
    """
    if not GROQ_API_KEY:
        return None
    try:
        import httpx
        with open(audio_path, "rb") as f:
            files = {"file": (os.path.basename(audio_path) or "audio.webm", f,
                              "application/octet-stream")}
            data: dict = {
                "model": GROQ_MODEL,
                "response_format": "verbose_json",
                "prompt": prompt(),
            }
            if lang:
                data["language"] = lang
            r = httpx.post(GROQ_URL, files=files, data=data,
                           headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                           timeout=GROQ_TIMEOUT)
        if r.status_code != 200:
            print(f"[Transcribe/Groq] {r.status_code}: {r.text[:200]}")
            return None
        j = r.json()
        return (j.get("text", "").strip(), j.get("language"))
    except Exception as e:
        # Network flake, DNS blip, quota — none of these are worth 500-ing
        # the request. Caller falls back to local Whisper.
        print(f"[Transcribe/Groq] failed: {e}")
        return None


def _run_local(audio_path: str, lang: str | None) -> tuple[str, str | None] | None:
    """One local-Whisper transcription. Returns (text, detected_lang) or None
    if the model cannot be loaded (no GPU, no weights, no package)."""
    model = _get_model()
    if model is None:
        return None
    segments, info = model.transcribe(
        audio_path,
        language=lang,
        initial_prompt=prompt(),
        beam_size=5,
        vad_filter=True,            # drops leading/trailing silence
    )
    return (" ".join(s.text for s in segments).strip(),
            getattr(info, "language", None))


def _run(audio_path: str, lang: str | None) -> tuple[str, str | None, str]:
    """Try backends in the configured order, return the first that produced text.

    Returns (text, detected_lang, backend_used).  backend_used is "unavailable"
    when every backend refused or errored — the frontend then falls back to the
    browser recogniser rather than showing an empty result.
    """
    for backend in _backend_order():
        result = _run_groq(audio_path, lang) if backend == "groq" \
                 else _run_local(audio_path, lang)
        if result and result[0]:
            return result[0], result[1], backend
    return "", None, "unavailable"


def transcribe(audio_path: str, ui_language: str | None = None) -> dict:
    """Transcribe an audio file, trying each configured backend in priority order.

    Returns {"text", "language", "available", "backend"} where backend is one of
    "groq" | "local" | None.

    NOTE — the language is deliberately NOT forced on the first attempt, even
    though the UI knows which one the user selected. Measured: auto-detect
    resolved 8/10 test utterances, forcing the selection resolved 6/10.
    Malaysian speech code-switches, and when Whisper settles on Malay it writes
    local names in Malay orthography ("Kerinci"), which the station matcher
    recognises; forced to English the same audio becomes "Karinji", which it
    does not. The same reasoning applies to Groq (same underlying model).
    """
    text, detected, backend = _run(audio_path, None)   # auto-detect first
    if backend == "unavailable":
        return {"text": "", "language": None, "available": False, "backend": None}

    # A transcript in the wrong script (Thai, Chinese) cannot match a station.
    # Retry with the language the user actually selected — same policy applies
    # whether the first pass came from Groq or local.
    if detected not in _PLAUSIBLE_LANGUAGES:
        fallback = ui_language if ui_language in _PLAUSIBLE_LANGUAGES else "ms"
        print(f"[Transcribe] detected {detected!r}, retrying as {fallback!r}")
        text2, det2, backend2 = _run(audio_path, fallback)
        if text2:
            text, detected, backend = text2, det2, backend2

    return {
        "text": text,
        "language": detected,
        "available": True,
        "backend": backend,
    }
