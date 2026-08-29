from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_root():
    assert client.get("/").json()["status"].startswith("LRT")


def test_reroute_endpoint():
    r = client.post("/api/reroute/find",
                    json={"origin": "KLCC", "destination": "KL SENTRAL"})
    assert r.status_code == 200
    body = r.json()
    assert "segments" in body and "routes" in body


def test_reroute_respects_preferences_payload():
    r = client.post("/api/reroute/find", json={
        "origin": "MASJID JAMEK", "destination": "KAJANG",
        "preferences": {"priority": "fewest_transfers", "prefer_shelter": True,
                        "avoid_lines": []},
    })
    assert r.status_code == 200
    assert r.json()["preferences_applied"]["priority"] == "fewest_transfers"


def test_stations_endpoint():
    data = client.get("/api/reroute/stations").json()
    assert len(data["stations"]) == 187   # 8 lines incl. LRT3


def test_govdata_endpoint():
    r = client.get("/api/govdata")
    assert r.status_code in (200, 404)    # 404 acceptable if cache not generated


def test_nlp_detect():
    r = client.post("/api/nlp/detect", json={"text": "MRT delay at Kajang again"})
    assert r.status_code == 200
    body = r.json()
    assert "sentiment" in body and "disruption_alert" in body


# ── Product-name typo correction ─────────────────────────────────────────────
# Retrieval survives a typo (surrounding words still match) but generation does
# not: the misspelled term is absent from the retrieved text, so the model
# correctly reports it knows nothing — refusing an answer the corpus contains.
# Reported: "my53 what is" was refused while citing the My50 FAQ.

def test_product_typo_is_corrected():
    from agents.rag_agent import _correct_terms
    assert _correct_terms("my53 what is")[0] == "my50 what is"
    assert _correct_terms("tell me about mutira pass")[0].endswith("mutiara pass")
    assert _correct_terms("kembera pass price")[0].startswith("kembara")


def test_correct_spelling_is_untouched():
    from agents.rag_agent import _correct_terms
    for q in ("what is the my50 pass", "how much is the kota pass"):
        assert _correct_terms(q) == (q, [])


def test_ordinary_words_are_not_rewritten():
    # the prefix rule is what makes a low similarity threshold safe
    from agents.rag_agent import _correct_terms
    for q in ("can I eat in the station", "kita boleh makan",
              "my card is lost", "musical instruments allowed",
              "pelan perjalanan", "emergency exit"):
        assert _correct_terms(q)[1] == [], q


def test_correction_is_disclosed_not_silent():
    # a confident answer about a DIFFERENT product is worse than a refusal if
    # the user never learns a substitution happened
    from agents.rag_agent import _correct_terms
    _, fixes = _correct_terms("my53 what is")
    assert fixes == [("my53", "my50")]


def test_vowel_substitution_is_corrected():
    # The most common error in Malay words is a swapped vowel, and a
    # two-character prefix rule blocked exactly that: "motira"/mutiara (77) and
    # "kumbara"/kembara (86) were never corrected. Safety comes from the
    # never-correct list instead of a strict prefix.
    from agents.rag_agent import _correct_terms
    assert _correct_terms("Motira Pass")[0].startswith("mutiara")
    assert _correct_terms("Kumbara Pass Price")[0].startswith("kembara")


def test_spaced_product_name_is_rejoined():
    # speech and casual typing split it: "my 53 watt is"
    from agents.rag_agent import _correct_terms
    assert _correct_terms("My 53 watt is")[0].startswith("my50")
    assert _correct_terms("how much is my 50 pass")[0] == "how much is my50 pass"


def test_everyday_malay_words_are_never_corrected():
    # "kotak" (box) scores 89 against "kota" and "kita" (we) scores 75 — both
    # are ordinary words a commuter types, and both leaked before the guard.
    from agents.rag_agent import _correct_terms
    for q in ("kotak makanan", "kita boleh makan", "kereta api",
              "berapa kos tiket", "my bag is lost", "my 2 friends"):
        assert _correct_terms(q)[1] == [], q


def test_no_control_characters_in_correction_patterns():
    # regression: an earlier edit wrote literal 0x08/0x01 bytes where \b and \1
    # were intended, so "my 53" was rewritten to "my" — silently deleting the
    # number rather than joining it.
    import agents.rag_agent as ra, inspect
    src = inspect.getsource(ra._correct_terms)
    assert "\x08" not in src and "\x01" not in src
