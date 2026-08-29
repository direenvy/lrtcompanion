"""
Measure whether local Whisper beats the browser's Web Speech API on Malaysian
station names — BEFORE committing to the rewrite.

The question is narrow. Chrome's recogniser returns English soundalikes for
local place names ("Kerinchi" -> "Karen chi", "Corinthian"), and fuzzy matching
cannot rescue those without also matching ordinary Malay words ("tadi" -> TTDI
at cutoff 75). Whisper is worth switching to ONLY if it reads those names
correctly — and the mechanism that should make it do so is `initial_prompt`,
which biases decoding toward a supplied vocabulary. Chrome has no equivalent:
the spec's SpeechGrammarList is a no-op there.

So this transcribes each recording twice — plain, and prompted with the station
list — and reports what the routing pipeline actually resolves in each case.
Resolution is what matters, not word-error rate: a transcript can be wrong and
still route correctly, and that already counts as a win.

Usage
-----
  python scripts/whisper_vs_webspeech.py record     # record phrases (one per prompt)
  python scripts/whisper_vs_webspeech.py run        # transcribe + compare
  python scripts/whisper_vs_webspeech.py            # record then run

Recordings live in data/eval/voice/*.wav and are kept, so a later run can be
compared against the same audio.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

AUDIO_DIR = ROOT / "data" / "eval" / "voice"
SAMPLE_RATE = 16_000          # what Whisper expects; avoids a resample step
RECORD_SECONDS = 8

# The phrases that matter: the ones Web Speech got wrong, plus a couple of
# controls that already work so a regression would be visible.
PHRASES = [
    ("kerinchi_klcc",      "I'm stuck at Kerinchi, I want to go to KLCC"),
    ("klcc_kerinchi_rev",  "I want to go to KLCC, I stopped at Kerinchi"),
    ("setiawangsa_jelatek","From Setiawangsa to Jelatek"),
    ("paramount_jamek",    "Taman Paramount to Masjid Jamek"),
    ("keramat_ampangpark", "Stuck at Dato Keramat going to Ampang Park"),
    ("kampungbaru_bintang","Kampung Baru to Bukit Bintang"),
    ("merdeka_klcc",       "From Merdeka to KLCC"),
    ("bahagia_kelana",     "Taman Bahagia to Kelana Jaya"),
    ("ms_universiti",      "Saya di Universiti nak ke Gombak"),
    ("ms_surian",          "Dari Surian ke Kajang"),
]


# Whisper conditions on `initial_prompt` as if it were text preceding the
# audio, but the decoder only accepts ~224 tokens of it and silently drops the
# rest. All 171 stations run to ~2,300 characters — far over — so the list has
# to be chosen, not dumped.
PROMPT_CHAR_BUDGET = 850

# Stations whose names ARE ordinary English words need no help: Whisper already
# has them in its priors, and spending prompt budget on them crowds out the
# names that actually get mangled.
_SAFE_IN_ENGLISH = {"university", "universiti", "central", "park", "garden",
                    "hospital", "airport", "terminal", "stadium", "museum"}


def _station_prompt(focus: list[str] | None = None) -> str:
    """Vocabulary hint for Whisper — the whole reason to expect an improvement.

    Prioritises names an English-trained model is least likely to guess:
    multi-word and unusual spellings first, plain English words last, trimmed
    to the prompt budget. `focus` puts specific names at the front, which is
    how a production build would bias toward a user's saved or nearby stations.
    """
    from api.dashboard import _STATION_NAMES, _CONDITIONAL_STATION_NAMES

    names = {n.title() for n in [*_STATION_NAMES, *_CONDITIONAL_STATION_NAMES]
             if len(n) > 3 and n.lower() not in _SAFE_IN_ENGLISH}

    def oddness(name: str) -> tuple:
        # crude but effective: unusual letter pairs and non-English shapes first
        exotic = sum(ch in "kqxyz" for ch in name.lower())
        return (-exotic, -len(name.split()), name)

    ordered = [*(focus or []), *sorted(names, key=oddness)]

    prefix = "Kuala Lumpur rail stations: "
    out, used = [], len(prefix) + 1             # + the trailing full stop
    for n in dict.fromkeys(ordered):            # dedupe, keep order
        if used + len(n) + 2 > PROMPT_CHAR_BUDGET:
            break
        out.append(n)
        used += len(n) + 2
    return prefix + ", ".join(out) + "."


def record() -> None:
    import sounddevice as sd
    import soundfile as sf

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nRecording {len(PHRASES)} phrases, {RECORD_SECONDS}s each.")
    print("Speak normally — do NOT over-enunciate; we are measuring real use.\n")

    for i, (slug, text) in enumerate(PHRASES, 1):
        path = AUDIO_DIR / f"{slug}.wav"
        input(f"[{i}/{len(PHRASES)}] Press Enter, then say:\n    \"{text}\"\n  > ")
        print("  ● recording…", end="", flush=True)
        audio = sd.rec(int(RECORD_SECONDS * SAMPLE_RATE),
                       samplerate=SAMPLE_RATE, channels=1, dtype="float32")
        sd.wait()
        sf.write(path, audio, SAMPLE_RATE)
        print(f" saved {path.name}")
    print(f"\nAll recordings in {AUDIO_DIR}\n")


def run() -> None:
    from faster_whisper import WhisperModel
    from api.voice import _stations_in_spoken_order, _assign_roles

    files = sorted(AUDIO_DIR.glob("*.wav"))
    if not files:
        print(f"No recordings in {AUDIO_DIR} — run `record` first.")
        return

    print("\nLoading Whisper large-v3 (int8_float16)…")
    t0 = time.time()
    # int8_float16 keeps large-v3 near 2 GB so it coexists with the backend,
    # the browser and a screen reader on a 6 GB laptop card.
    model = WhisperModel("large-v3", device="cuda", compute_type="int8_float16")
    print(f"  loaded in {time.time() - t0:.1f}s")

    # Bias toward the stations these recordings actually name — this is the
    # realistic production case too (a live build would seed the prompt from
    # the user's saved home/work stations and the lines near them).
    focus = sorted({
        "Kerinchi", "Setiawangsa", "Jelatek", "Taman Paramount", "Masjid Jamek",
        "Dato' Keramat", "Ampang Park", "Kampung Baru", "Bukit Bintang",
        "Merdeka", "Taman Bahagia", "Kelana Jaya", "Universiti", "Gombak",
        "Surian", "Kajang", "KLCC",
    })
    prompt = _station_prompt(focus)
    print(f"  vocabulary hint: {len(prompt)} chars\n")

    expected = dict(PHRASES)
    rows, wins = [], 0

    for path in files:
        slug = path.stem
        said = expected.get(slug, "(unknown phrase)")

        def transcribe(hint: str | None) -> tuple[str, float]:
            t = time.time()
            # language=None (auto-detect) is deliberate and MEASURED — do not
            # "fix" this by forcing the user's selected language. Measured on
            # these ten recordings: auto-detect resolved 8/10, forcing the
            # language resolved 6/10. Malaysian speech code-switches, and when
            # Whisper settles on Malay it renders local names in Malay
            # orthography ("Kerinci"), which the station matcher recognises;
            # forced to English the same audio becomes "Karinji", which it does
            # not. The recogniser choosing the language is a feature here.
            segs, _ = model.transcribe(
                str(path), language=None, initial_prompt=hint,
                beam_size=5, vad_filter=True,
            )
            return " ".join(s.text for s in segs).strip(), time.time() - t

        plain, t_plain = transcribe(None)
        hinted, t_hint = transcribe(prompt)

        def resolve(text: str):
            st = _stations_in_spoken_order(text)
            if len(st) < 2:
                return st, None
            return st, (_assign_roles(text, st) or (st[0], st[-1]))

        st_p, route_p = resolve(plain)
        st_h, route_h = resolve(hinted)
        if route_h and not route_p:
            wins += 1

        rows.append((slug, said, plain, hinted, route_p, route_h, t_plain, t_hint))

        print(f"── {slug}")
        print(f"   said     : {said}")
        print(f"   plain    : {plain}")
        print(f"     -> {route_p or st_p or 'no stations'}")
        print(f"   prompted : {hinted}")
        print(f"     -> {route_h or st_h or 'no stations'}")
        print(f"   {t_plain:.2f}s / {t_hint:.2f}s\n")

    ok_p = sum(1 for r in rows if r[4])
    ok_h = sum(1 for r in rows if r[5])
    n = len(rows)
    avg = sum(r[7] for r in rows) / n

    print("=" * 62)
    print(f"  resolved to a full trip, plain    : {ok_p}/{n}")
    print(f"  resolved to a full trip, prompted : {ok_h}/{n}")
    print(f"  rescued by the vocabulary hint    : {wins}")
    print(f"  mean transcription time           : {avg:.2f}s")
    print("=" * 62)
    print("\nCompare against what Chrome gave you for the same phrases.")
    print("Whisper is worth the rewrite only if it clearly resolves more.\n")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("record", "all"):
        record()
    if cmd in ("run", "all"):
        run()
