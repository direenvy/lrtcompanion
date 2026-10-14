"""
Voice assistant tests — transcript in, spoken-friendly reply out.
Fully offline: STT happens in the browser; Supabase + line-status are
patched in conftest.py.
"""
from api.voice import assist, VoiceRequest, _stations_in_spoken_order, _assign_roles


def test_stations_extracted_in_spoken_order():
    assert _stations_in_spoken_order(
        "i am stuck at kampung baru and i want to go to masjid jamek"
    ) == ["KAMPUNG BARU", "MASJID JAMEK"]
    # longest-first: 'ampang park' must not double-match as 'ampang'
    assert _stations_in_spoken_order(
        "stuck at ampang park going to ampang"
    ) == ["AMPANG PARK", "AMPANG"]


def test_full_sentence_returns_route_and_reply():
    out = assist(VoiceRequest(
        text="I'm stuck at Kampung Baru, I want to go to Masjid Jamek"))
    assert out["origin"] == "KAMPUNG BARU"
    assert out["destination"] == "MASJID JAMEK"
    assert out["route"]["estimated_minutes"] > 0
    assert "Board the" in out["reply"]           # instructions are spoken
    assert out["reply"].startswith("I have reported the problem")


def test_no_station_asks_where_they_are():
    out = assist(VoiceRequest(text="help me the train is not moving"))
    assert out["need_station"] is True
    assert "which station" in out["reply"].lower()


def test_one_station_asks_for_destination():
    out = assist(VoiceRequest(text="i am stuck at wangsa maju"))
    assert out["need_destination"] is True
    assert out["origin"] == "WANGSA MAJU"


def test_origin_hint_completes_the_follow_up_turn():
    out = assist(VoiceRequest(text="i want to go to klcc",
                              origin_hint="WANGSA MAJU"))
    assert out["origin"] == "WANGSA MAJU"
    assert out["destination"] == "KLCC"
    assert out["route"]["estimated_minutes"] > 0


def test_non_disruption_question_gets_route_without_report_ack():
    out = assist(VoiceRequest(text="how do i go from klcc to masjid jamek"))
    assert out["destination"] == "MASJID JAMEK"
    assert not out["reply"].startswith("I have reported")


def test_malay_reply_full_route():
    out = assist(VoiceRequest(
        text="saya tersekat di kampung baru, nak pergi ke masjid jamek",
        lang="ms"))
    assert out["origin"] == "KAMPUNG BARU"
    assert out["destination"] == "MASJID JAMEK"
    assert "Naik" in out["reply"] and "minit" in out["reply"]
    assert "Board the" not in out["reply"]        # no English leakage


def test_malay_follow_up_prompts():
    out = assist(VoiceRequest(text="tolong, tren rosak", lang="ms"))
    assert out["need_station"] is True
    assert "stesen" in out["reply"].lower()
    out2 = assist(VoiceRequest(text="saya di wangsa maju", lang="ms"))
    assert out2["need_destination"] is True
    assert "pergi ke stesen mana" in out2["reply"].lower()


def test_malay_transfer_instruction():
    out = assist(VoiceRequest(
        text="saya di chow kit mahu ke ampang", lang="ms"))
    assert "tukar ke platform" in out["reply"]    # interchange spoken in Malay


def test_spoken_names_have_no_sponsor_suffix():
    for lang in ("en", "ms"):
        out = assist(VoiceRequest(
            text="stuck at kampung baru going to masjid jamek", lang=lang))
        assert "COOPBANK" not in out["reply"]
        assert "Kampung Baru" in out["reply"] or "KAMPUNG BARU" not in out["reply"]


def test_fuzzy_matching_handles_speech_mistranscriptions():
    # Chrome STT mangles Malaysian names — the extractor must still resolve them
    assert _stations_in_spoken_order("i'm stuck at ampong station") == ["AMPANG"]
    assert _stations_in_spoken_order(
        "stuck at kampong baru going to masjid jamek"
    ) == ["KAMPUNG BARU", "MASJID JAMEK"]
    # ...but junk sentences must NOT fuzzy-match into phantom stations
    assert _stations_in_spoken_order("help me the train is not moving") == []
    assert _stations_in_spoken_order("i will stop at") == []


def test_fuzzy_full_reply_from_mistranscribed_speech():
    out = assist(VoiceRequest(text="i'm stuck at ampong station, i want to go to sentul"))
    assert out["origin"] == "AMPANG"
    assert out["destination"] == "SENTUL"
    assert out["route"]["estimated_minutes"] > 0


def test_service_question_hands_off_to_rag(monkeypatch):
    import agents.rag_agent as rag
    monkeypatch.setattr(rag, "answer",
        lambda q, top_k=4, history=None: {"answer": "**My50** is RM50 for 30 days.", "mode": "semantic"})
    out = assist(VoiceRequest(text="what is the my50 monthly pass"))
    assert out["mode"] == "chat"
    assert "My50 is RM50" in out["reply"]      # markdown stripped for speech
    assert "**" not in out["reply"]


def test_rag_unavailable_falls_back_to_station_prompt():
    # conftest stubs RAG to an empty answer -> graceful fall-through
    out = assist(VoiceRequest(text="tell me something about the weather"))
    assert out.get("need_station") is True


# ── Common-word station names in spoken journey requests ─────────────────────
# "merdeka" / "universiti" / "subang" are also everyday words. In a voice turn
# the cue that one is a PLACE is a positional preposition ("at X", "di X"), not
# a disruption verb (that gate belongs to the report path in dashboard.py).

def test_common_word_station_found_after_preposition():
    assert "MERDEKA" in _stations_in_spoken_order("from Merdeka to KLCC")
    assert "UNIVERSITI" in _stations_in_spoken_order("saya di Universiti nak ke Gombak")
    assert "SUBANG" in _stations_in_spoken_order("I'm at Subang going to KL Sentral")


def test_common_word_station_found_in_origin_position():
    # no leading preposition, but "<name> to <somewhere>" marks it as origin
    assert _stations_in_spoken_order("Merdeka to Ampang Park")[:1] == ["MERDEKA"]


def test_common_word_station_found_with_malay_prepositions():
    got = _stations_in_spoken_order("dari Surian ke Kajang")
    assert got == ["SURIAN", "KAJANG"]


def test_ordinary_speech_does_not_yield_common_word_station():
    for phrase in ("hari merdeka celebration",
                   "kerja dekat sini",
                   "cahaya matahari sangat cantik",
                   "my university is far"):
        assert _stations_in_spoken_order(phrase) == [], phrase


def test_preposition_must_be_a_whole_word():
    # "berlin merdeka" contains "in merdeka" — a missing word boundary here
    # would turn any word ending in a preposition into a false match.
    assert "MERDEKA" not in _stations_in_spoken_order("berlin merdeka square")


def test_journey_pattern_has_no_control_characters():
    # regression: an earlier edit wrote literal backspace bytes (0x08) where
    # the regex \b was intended, so the guard silently never matched.
    import api.voice as v
    assert "\x08" not in v._JOURNEY_POSITION


# ── N-best hypothesis selection ──────────────────────────────────────────────
# Browsers return a RANKED LIST of readings. For Malaysian place names the top
# reading is often an English soundalike, so every hypothesis is tested and the
# one that actually resolves to stations wins.

def test_alternative_beats_a_top_reading_that_resolves_to_nothing():
    from api.voice import _best_transcript
    # The primary must be a mishearing the confusion dictionary does NOT cover,
    # or the dictionary rescues it and this stops testing N-best selection.
    text, stations = _best_transcript("Cornish tomato seed", ["Kerinchi to KLCC"])
    assert stations == ["KERINCHI", "KLCC"]
    assert text == "Kerinchi to KLCC"


def test_exact_spelling_outranks_a_fuzzy_hit():
    # both readings yield two stations, but the fuzzy one resolves WRONGLY
    # ("car pong bar" -> KEPONG BARU). Spelling it out must win.
    from api.voice import _best_transcript
    _, stations = _best_transcript(
        "I'm stuck at car pong bar to mas jid jamek",
        ["I'm stuck at Kampung Baru to Masjid Jamek"],
    )
    assert stations == ["KAMPUNG BARU", "MASJID JAMEK"]


def test_good_primary_is_not_replaced():
    from api.voice import _best_transcript
    text, stations = _best_transcript("from Kerinchi to KLCC", ["junk one", "junk two"])
    assert text == "from Kerinchi to KLCC"
    assert stations == ["KERINCHI", "KLCC"]


def test_alternative_supplying_both_endpoints_wins():
    from api.voice import _best_transcript
    _, stations = _best_transcript("Gombak", ["Gombak to Kajang"])
    assert stations == ["GOMBAK", "KAJANG"]


def test_falls_back_to_primary_when_nothing_resolves():
    from api.voice import _best_transcript
    text, stations = _best_transcript("blah blah blah", ["more nonsense"])
    assert text == "blah blah blah"
    assert stations == []


def test_no_alternatives_behaves_as_before():
    from api.voice import _best_transcript
    text, stations = _best_transcript("from Gombak to Kajang", [])
    assert text == "from Gombak to Kajang"
    assert stations == ["GOMBAK", "KAJANG"]


def test_assist_accepts_alternatives_end_to_end():
    r = assist(VoiceRequest(text="Corinthian to KLCC",
                            alternatives=["Kerinchi to KLCC"]))
    assert "reply" in r
    assert "KERINCHI" in str(r).upper()


# ── Journey direction ────────────────────────────────────────────────────────
# Role must come from the preposition, not from word order: people lead with
# their destination as often as their origin.

def test_destination_first_phrasing_is_not_reversed():
    # reported failure: this answered "you are at KLCC"
    text = "I want to go to klcc I stopped at Kerinchi"
    assert _assign_roles(text, _stations_in_spoken_order(text)) == ("KERINCHI", "KLCC")


def test_origin_first_phrasing_still_works():
    text = "I'm stuck at Kerinchi, I want to go to KLCC"
    assert _assign_roles(text, _stations_in_spoken_order(text)) == ("KERINCHI", "KLCC")


def test_markers_beat_order_in_both_directions():
    for text in ("to KLCC from Kerinchi", "from Kerinchi to KLCC"):
        assert _assign_roles(text, _stations_in_spoken_order(text)) == ("KERINCHI", "KLCC")


def test_malay_markers_assign_direction():
    text = "saya nak ke Gombak, saya di Universiti"
    assert _assign_roles(text, _stations_in_spoken_order(text)) == ("UNIVERSITI", "GOMBAK")


def test_one_marked_end_is_enough():
    text = "going to Gombak, Kajang"
    assert _assign_roles(text, _stations_in_spoken_order(text)) == ("KAJANG", "GOMBAK")


def test_no_markers_falls_back_to_spoken_order():
    # unmarked: caller keeps the positional reading rather than guessing
    assert _assign_roles("Kerinchi KLCC", ["KERINCHI", "KLCC"]) is None


def test_everyday_words_do_not_fuzzy_match_stations():
    # "only" scores 80 against CONLAY, "tadi" 75 against TTDI — both are common
    # speech and must never hijack a trip.
    for phrase in ("I only want to go", "tadi saya tunggu lama"):
        assert _stations_in_spoken_order(phrase) == [], phrase


# ── Local Whisper transcription ──────────────────────────────────────────────
# The model itself is never loaded in tests: weights are ~1.5 GB and need a GPU,
# so the suite must stay offline and fast. What is pinned here is the CONTRACT —
# graceful degradation, and the measured decisions that are easy to "tidy" away.

def test_stt_status_reports_without_loading_a_model(monkeypatch):
    import agents.transcribe_agent as ta
    from api.voice import stt_status
    monkeypatch.setattr(ta, "available", lambda: False)
    monkeypatch.setattr(ta, "load_error", lambda: "no CUDA device")
    out = stt_status()
    assert out["available"] is False
    assert out["error"] == "no CUDA device"


def test_transcribe_returns_unavailable_rather_than_raising(monkeypatch):
    import agents.transcribe_agent as ta
    # local-only, and the local model cannot load — must degrade, not raise
    monkeypatch.setattr(ta, "BACKEND", "local")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "")
    monkeypatch.setattr(ta, "_model", None)
    monkeypatch.setattr(ta, "_load_error", "faster_whisper not installed")
    out = ta.transcribe("nonexistent.wav")
    assert out == {"text": "", "language": None, "available": False, "backend": None}


def test_prompt_fits_whispers_token_budget():
    import agents.transcribe_agent as ta
    p = ta._build_prompt()
    # Whisper reads ~224 tokens of initial_prompt and silently drops the rest,
    # so an over-long prompt fails invisibly.
    assert 0 < len(p) <= ta.PROMPT_CHAR_BUDGET


def test_prompt_prefers_names_english_would_not_guess():
    import agents.transcribe_agent as ta
    p = ta._build_prompt().lower()
    # budget is tight, so it must spend it on the hard names, not on words
    # Whisper already knows
    assert "kerinchi" in p or "kelana jaya" in p
    assert "university" not in p


def test_language_is_not_forced(monkeypatch):
    # Measured: auto-detect resolved 8/10 test utterances, forcing the user's
    # selected language resolved 6/10 — Malay orthography ("Kerinci") matches
    # the station list where English ("Karinji") does not. Guard the decision.
    import agents.transcribe_agent as ta
    seen = {}

    class FakeModel:
        def transcribe(self, path, **kw):
            seen.update(kw)
            class S: text = "from Kerinchi to KLCC"
            class I: language = "en"
            return [S()], I()

    monkeypatch.setattr(ta, "_model", FakeModel())
    monkeypatch.setattr(ta, "_load_error", None)
    out = ta.transcribe("x.wav")
    assert seen["language"] is None, "language must stay auto-detected"
    assert seen["initial_prompt"], "station vocabulary hint must be sent"
    assert out["text"] == "from Kerinchi to KLCC"


# ── Confusion dictionary ─────────────────────────────────────────────────────
# Mishearings that matter cluster at 71-77 similarity — just under the fuzzy
# cutoff — and the gap cannot be closed by lowering it (that admits "tadi" ->
# TTDI). Specific observed substitutions are corrected by name instead.

def test_observed_mishearings_resolve_to_the_right_station():
    cases = {
        "Pergi ke gelatik":                            "JELATEK",   # a bird
        "Setakat setia wangsa, napagi celate.":        "JELATEK",
        "From Odegaard to KLCC":                       "MERDEKA",
        "Dari Suryang ke Kajang":                      "SURIAN",
        "Corinthian to KLCC":                          "KERINCHI",
        "I am stuck at Karinji. I want to go to KLCC": "KERINCHI",
    }
    for text, station in cases.items():
        assert station in _stations_in_spoken_order(text), text


def test_correction_applies_before_direction_is_read():
    # _assign_roles searches the text for each station's span; without the same
    # correction a rescued name has no span and direction silently falls back
    # to spoken order.
    text = "Setakat setia wangsa, napagi celate."
    st = _stations_in_spoken_order(text)
    assert _assign_roles(text, st) == ("SETIAWANGSA", "JELATEK")


def test_correction_does_not_weaken_the_false_positive_guard():
    assert _stations_in_spoken_order("hari merdeka celebration") == []


def test_correction_is_whole_word_only():
    # substring replacement would corrupt unrelated words
    import api.voice as v
    assert v._fix_mishearings("regelatiko") == "regelatiko"
    assert v._fix_mishearings("gelatik") == "jelatek"


def test_every_mishearing_targets_a_real_station():
    import api.voice as v
    from api.dashboard import _STATION_NAMES, _CONDITIONAL_STATION_NAMES
    known = {*_STATION_NAMES, *_CONDITIONAL_STATION_NAMES}
    for heard, meant in v._STT_MISHEARINGS.items():
        assert meant in known, f"{heard!r} -> {meant!r} is not a station"


def test_taman_paramount_mishearings_resolve():
    # "Taman" itself is unstable in transcription; once it goes the whole name
    # drops to ~69 similarity and no scorer recovers it safely.
    for text in ("Tawang Palamao tu Masjid Jamek.", "Nama Pramau", "Sama Pramau"):
        assert "TAMAN PARAMOUNT" in _stations_in_spoken_order(text), text


def test_wild_language_detection_is_retried(monkeypatch):
    # Auto-detect has landed on Thai and Chinese for Malay speech. A transcript
    # in the wrong script cannot match any station, so the turn is lost unless
    # it is retried against the language the user selected.
    import agents.transcribe_agent as ta
    calls = []

    class FakeModel:
        def transcribe(self, path, **kw):
            calls.append(kw["language"])
            class S:
                text = "ตามบรมเมาท์" if kw["language"] is None else "Taman Paramount"
            class I:
                language = "th" if kw["language"] is None else kw["language"]
            return [S()], I()

    monkeypatch.setattr(ta, "_model", FakeModel())
    monkeypatch.setattr(ta, "_load_error", None)
    out = ta.transcribe("x.wav", ui_language="ms")
    assert calls == [None, "ms"], "should auto-detect first, then retry"
    assert out["text"] == "Taman Paramount"


def test_plausible_detection_is_not_retried(monkeypatch):
    import agents.transcribe_agent as ta
    calls = []

    class FakeModel:
        def transcribe(self, path, **kw):
            calls.append(kw["language"])
            class S: text = "from Kerinchi to KLCC"
            class I: language = "en"
            return [S()], I()

    monkeypatch.setattr(ta, "_model", FakeModel())
    monkeypatch.setattr(ta, "_load_error", None)
    ta.transcribe("x.wav", ui_language="ms")
    assert calls == [None], "a plausible detection must not trigger a second pass"


# ── "Did you mean X?" — near-miss confirmation ───────────────────────────────
# Below the fuzzy cutoff a match is not safe to ACT on, but measured over the
# mishearings collected in testing the intended station was still the top
# candidate 5 times in 8 and in the top three 7 times in 8. So the band is
# offered as a question instead of guessed at — safer than a silent wrong
# route, and unlike repeating "which station?" it escapes the loop.

def test_near_miss_is_offered_not_guessed():
    from api.voice import _suggest_station
    assert _suggest_station("Jelati", [])[0] == "JELATEK"
    assert _suggest_station("pergi ke jodate", [])[0] == "JELATEK"


def test_confident_input_is_never_questioned():
    from api.voice import _suggest_station
    text = "from Kerinchi to KLCC"
    assert _suggest_station(text, _stations_in_spoken_order(text)) is None
    assert assist(VoiceRequest(text=text)).get("pending_station") is None


def test_partial_resolution_offers_the_missing_end():
    # the reported loop: origin resolved, destination misheard, and repeating
    # "which station?" could not escape because the name is misheard the same
    # way every time
    r = assist(VoiceRequest(text="Dari Setiawangsak ke Jodate"))
    assert r["pending_station"] == "JELATEK"
    assert "Jelatek" in r["reply"]


def test_yes_accepts_the_offered_station():
    r = assist(VoiceRequest(text="ya", origin_hint="SETIAWANGSA",
                            pending_station="JELATEK", lang="ms"))
    assert "Jelatek" in r["reply"]
    assert r.get("need_destination") is not True


def test_yes_without_a_pending_offer_does_nothing():
    r = assist(VoiceRequest(text="yes"))
    assert r.get("origin") is None


def test_affirmative_recognised_in_both_languages():
    from api.voice import _is_affirmative
    for w in ("yes", "yeah", "ok", "ya", "betul", "boleh"):
        assert _is_affirmative(w), w
    for w in ("no", "tidak", "Kerinchi", "go to KLCC"):
        assert not _is_affirmative(w), w


# ── Repeated mentions must not become different stations ─────────────────────
# Speech repeats constantly, and Whisper duplicates whole phrases of its own
# accord. A fragment whose best reading is already accounted for is a SECOND
# MENTION — offering its runner-up instead routed a user to the wrong station.

def test_repeated_phrase_does_not_invent_a_second_station():
    # reported: "ampung Baru" (truncated repeat, best match KAMPUNG BARU at 96)
    # was handed its runner-up KAMPUNG BATU (87) because the exact pass had
    # already claimed KAMPUNG BARU — the user was routed to the wrong station.
    text = "ampung Baru ke Bukit Bintang. Kampung Baru ke Bukit Bintang."
    got = _stations_in_spoken_order(text)
    assert sorted(got) == ["BUKIT BINTANG", "KAMPUNG BARU"]
    assert "KAMPUNG BATU" not in got


def test_repeat_words_are_blocked_from_shorter_passes():
    # dropping the two-word repeat must not free "ampung" to match AMPANG
    text = "ampung Baru ke Bukit Bintang. Kampung Baru ke Bukit Bintang."
    assert "AMPANG" not in _stations_in_spoken_order(text)


def test_direction_survives_a_repeated_sentence():
    text = "ampung Baru ke Bukit Bintang. Kampung Baru ke Bukit Bintang."
    st = _stations_in_spoken_order(text)
    assert _assign_roles(text, st) == ("KAMPUNG BARU", "BUKIT BINTANG")


def test_two_genuinely_similar_stations_still_both_resolve():
    # the guard must not collapse real pairs: Kampung Baru and Kampung Batu are
    # different stations and a trip between them is legitimate
    got = _stations_in_spoken_order(
        "I'm stuck at Kampung Baru and I want to go to Kampung Batu")
    assert sorted(got) == ["KAMPUNG BARU", "KAMPUNG BATU"]


def test_whisper_style_duplicate_output_resolves_once():
    got = _stations_in_spoken_order(
        "Taman bahagia tu kerana jaya. Taman bahagia tu kerana jaya.")
    assert sorted(got) == ["KELANA JAYA", "TAMAN BAHAGIA"]


# ── Backend selection (Groq vs local) ────────────────────────────────────────
# The hosted deployment (Render, no GPU) uses Groq; the local machine uses
# faster-whisper. Neither the real model nor a real network call is exercised
# here — only the SELECTION logic and graceful fallback.

def test_backend_order_local_only(monkeypatch):
    import agents.transcribe_agent as ta
    monkeypatch.setattr(ta, "BACKEND", "local")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "gsk_dummy")
    assert ta._backend_order() == ["local"]


def test_backend_order_groq_falls_back_to_local(monkeypatch):
    import agents.transcribe_agent as ta
    monkeypatch.setattr(ta, "BACKEND", "groq")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "gsk_dummy")
    assert ta._backend_order() == ["groq", "local"]


def test_backend_order_groq_without_key_is_local(monkeypatch):
    import agents.transcribe_agent as ta
    monkeypatch.setattr(ta, "BACKEND", "groq")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "")
    assert ta._backend_order() == ["local"]


def test_auto_picks_groq_when_key_present(monkeypatch):
    import agents.transcribe_agent as ta
    monkeypatch.setattr(ta, "BACKEND", "auto")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "gsk_dummy")
    assert ta._backend_order()[0] == "groq"


def test_available_true_when_groq_key_present(monkeypatch):
    # available() must be cheap — presence of the key counts, no live probe,
    # no cold-loading the local model (that would block the status poll).
    import agents.transcribe_agent as ta
    monkeypatch.setattr(ta, "BACKEND", "groq")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "gsk_dummy")
    assert ta.available() is True


def test_transcribe_uses_groq_first(monkeypatch):
    import agents.transcribe_agent as ta
    monkeypatch.setattr(ta, "BACKEND", "groq")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "gsk_dummy")
    monkeypatch.setattr(ta, "_run_groq", lambda p, l: ("from Kerinchi to KLCC", "en"))
    monkeypatch.setattr(ta, "_run_local", lambda p, l: (_ for _ in ()).throw(AssertionError("local should not run")))
    out = ta.transcribe("x.webm")
    assert out["backend"] == "groq"
    assert out["text"] == "from Kerinchi to KLCC"


def test_transcribe_falls_back_to_local_when_groq_fails(monkeypatch):
    import agents.transcribe_agent as ta
    monkeypatch.setattr(ta, "BACKEND", "groq")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "gsk_dummy")
    monkeypatch.setattr(ta, "_run_groq", lambda p, l: None)          # Groq down
    monkeypatch.setattr(ta, "_run_local", lambda p, l: ("from Gombak to Kajang", "en"))
    out = ta.transcribe("x.webm")
    assert out["backend"] == "local"
    assert out["text"] == "from Gombak to Kajang"


def test_transcribe_reports_unavailable_when_all_backends_fail(monkeypatch):
    import agents.transcribe_agent as ta
    monkeypatch.setattr(ta, "BACKEND", "groq")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "gsk_dummy")
    monkeypatch.setattr(ta, "_run_groq", lambda p, l: None)
    monkeypatch.setattr(ta, "_run_local", lambda p, l: None)
    out = ta.transcribe("x.webm")
    assert out == {"text": "", "language": None, "available": False, "backend": None}


def test_wild_language_retry_still_works_through_backends(monkeypatch):
    # the Thai/Chinese retry policy must survive the backend refactor
    import agents.transcribe_agent as ta
    calls = []
    def fake_run(p, lang):
        calls.append(lang)
        return ("ตามบรมเมาท์", "th") if lang is None else ("Taman Paramount", "en")
    monkeypatch.setattr(ta, "BACKEND", "groq")
    monkeypatch.setattr(ta, "GROQ_API_KEY", "gsk_dummy")
    monkeypatch.setattr(ta, "_run_groq", fake_run)
    out = ta.transcribe("x.webm", ui_language="ms")
    assert calls == [None, "ms"]
    assert out["text"] == "Taman Paramount"


# ── /resolve-stations — voice fills the Plan Trip fields ─────────────────────
# Same resolution stack as /assist but WITHOUT routing, so the Plan Trip page
# keeps its own preference controls and route rendering.

def test_resolve_fills_both_stations():
    from api.voice import resolve_stations, ResolveRequest
    r = resolve_stations(ResolveRequest(text="I'm stuck at Kerinchi, I want to go to KLCC"))
    assert (r["origin"], r["destination"]) == ("KERINCHI", "KLCC")


def test_resolve_respects_direction_not_word_order():
    # destination stated first must NOT become the origin
    from api.voice import resolve_stations, ResolveRequest
    r = resolve_stations(ResolveRequest(text="I want to go to KLCC, I stopped at Kerinchi"))
    assert (r["origin"], r["destination"]) == ("KERINCHI", "KLCC")


def test_resolve_handles_malay():
    from api.voice import resolve_stations, ResolveRequest
    r = resolve_stations(ResolveRequest(text="saya di Universiti nak ke Gombak"))
    assert (r["origin"], r["destination"]) == ("UNIVERSITI", "GOMBAK")


def test_resolve_single_station_returns_origin_only():
    # guessing which end the user meant would be worse than asking
    from api.voice import resolve_stations, ResolveRequest
    r = resolve_stations(ResolveRequest(text="from Gombak"))
    assert r["origin"] == "GOMBAK"
    assert r["destination"] is None


def test_resolve_offers_near_miss_suggestion():
    from api.voice import resolve_stations, ResolveRequest
    r = resolve_stations(ResolveRequest(text="pergi ke jelati"))
    assert r["suggestion"] == "JELATEK"


def test_resolve_empty_when_nothing_matches():
    from api.voice import resolve_stations, ResolveRequest
    r = resolve_stations(ResolveRequest(text="hello how are you"))
    assert r["origin"] is None and r["destination"] is None and r["suggestion"] is None


# ── Intent gate on the voice path ────────────────────────────────────────────
# "I want to go to Mid Valley" logged as a breakdown is where this bug was
# first noticed. The acknowledgement matters as much as the log row: an
# assistant that says "I have reported the problem" when no alert was recorded
# is telling the user something untrue about its own behaviour.

import agents.intent_gate as gate
import api.voice as voice_api


def test_navigation_request_is_not_acknowledged_as_a_report(monkeypatch):
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "_call_gemini",
                        lambda p, t=None: '{"live": false, "why": "navigation request"}')
    logged = []
    monkeypatch.setattr(voice_api, "log_disruption",
                        lambda **kw: logged.append(kw))
    monkeypatch.setattr(voice_api, "predict", lambda t, allow_remote=True: {
        "sentiment": "negative", "issue_type": "breakdown",
        "disruption_alert": True, "method": "local",
        "sentiment_scores": {}, "issue_scores": {}})

    out = assist(VoiceRequest(
        text="I'm stuck at Kampung Baru, I want to go to Masjid Jamek"))
    assert logged[0]["disruption_alert"] is False
    assert logged[0]["method"].endswith("+gate_filtered")
    # the route is still planned — the user still gets what they asked for
    assert out["origin"] == "KAMPUNG BARU"
    assert not out["reply"].startswith("I have reported the problem")


def test_a_real_spoken_report_is_still_acknowledged(monkeypatch):
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(gate, "_call_gemini",
                        lambda p, t=None: '{"live": true, "why": "stuck on platform"}')
    monkeypatch.setattr(voice_api, "log_disruption", lambda **kw: None)

    out = assist(VoiceRequest(
        text="I'm stuck at Kampung Baru, I want to go to Masjid Jamek"))
    assert out["reply"].startswith("I have reported the problem")


def test_voice_uses_a_shorter_timeout_than_the_batch_path(monkeypatch):
    """The user is waiting. The Gemini classifier refinement was already
    removed from this path because it cost ~9 s; the gate must not
    reintroduce the same problem."""
    from agents.intent_gate import GATE_TIMEOUT_SECONDS, VOICE_TIMEOUT_SECONDS
    assert VOICE_TIMEOUT_SECONDS < GATE_TIMEOUT_SECONDS

    monkeypatch.setattr(gate, "INTENT_GATE", True)
    seen = []
    monkeypatch.setattr(gate, "_call_gemini",
                        lambda p, t=None: seen.append(t) or '{"live": true}')
    monkeypatch.setattr(voice_api, "log_disruption", lambda **kw: None)
    monkeypatch.setattr(voice_api, "predict", lambda t, allow_remote=True: {
        "sentiment": "negative", "issue_type": "breakdown",
        "disruption_alert": True, "method": "local",
        "sentiment_scores": {}, "issue_scores": {}})

    assist(VoiceRequest(text="stuck at kampung baru going to masjid jamek"))
    assert seen == [VOICE_TIMEOUT_SECONDS]


def test_gate_outage_still_acknowledges_the_report(monkeypatch):
    """Fails open — both providers blocked by conftest. Under-reporting a real
    disruption is the worse error, and silently dropping the acknowledgement
    would make the user repeat themselves."""
    monkeypatch.setattr(gate, "INTENT_GATE", True)
    monkeypatch.setattr(voice_api, "log_disruption", lambda **kw: None)

    out = assist(VoiceRequest(
        text="I'm stuck at Kampung Baru, I want to go to Masjid Jamek"))
    assert out["reply"].startswith("I have reported the problem")
