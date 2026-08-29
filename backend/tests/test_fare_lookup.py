"""
Fare-lookup tests — fully offline; reads the committed fare CSVs.
Expected values come straight from the official matrices.
"""
import agents.fare_lookup as fl


def test_integrated_pair_cash_and_cashless():
    ans = fl.try_answer("How much is the fare from Gombak to Kajang?")
    assert ans is not None
    assert "RM6.60" in ans          # cash (official matrix)
    assert "RM5.60" in ans          # cashless
    assert "Gombak" in ans and "Kajang" in ans


def test_longest_name_wins_over_substring():
    # 'Stadium Kajang' must not be matched as 'Kajang'
    ans = fl.try_answer("fare from Stadium Kajang to Gombak?")
    assert ans is not None
    assert "RM7.30" in ans          # Stadium Kajang→Gombak cash, not Kajang's 6.60


def test_symmetry_order_does_not_matter():
    a = fl.try_answer("fare from Gombak to Kajang")
    b = fl.try_answer("fare from Kajang to Gombak")
    assert "RM6.60" in a and "RM6.60" in b


def test_sal_pair_includes_concession():
    ans = fl.try_answer("How much from Bandar Utama to Johan Setia?")
    assert ans is not None
    assert "Shah Alam" in ans
    assert "RM4.90" in ans          # cash
    assert "RM4.30" in ans          # cashless
    assert "RM2.40" in ans          # concession


def test_cross_network_sums_both_fares():
    ans = fl.try_answer("fare from Johan Setia to KLCC?")
    assert ans is not None
    assert "two fares" in ans
    assert "Bandar Utama" in ans    # explains the transfer
    # SAL Johan Setia→Bandar Utama cash 4.90 + integrated Bandar Utama→KLCC cash 4.70
    assert "RM9.60" in ans


def test_non_fare_question_returns_none():
    assert fl.try_answer("What are the operating hours of the LRT?") is None
    assert fl.try_answer("Is the Kelana Jaya line disrupted?") is None


def test_single_station_returns_none():
    assert fl.try_answer("How much is a fare at KLCC?") is None


def test_malay_fare_question():
    ans = fl.try_answer("Berapa tambang dari Gombak ke Kajang?")
    assert ans is not None
    assert "RM6.60" in ans


# ── Speech-to-text spellings ─────────────────────────────────────────────────
# Transcripts arrive in whichever orthography the recogniser settled on. An
# exact table lookup then finds nothing and a question the fare data answers
# EXACTLY falls through to RAG, which refuses it.

def test_malay_spelling_from_transcription_still_finds_the_fare():
    a = fl.try_answer("Berapa tambang ia dari Kerinci ke KLCC?")   # Whisper: "Kerinci"
    assert a and "RM" in a and "Kerinchi" in a


def test_fuzzy_pass_does_not_invent_fares():
    # A wrong fare is worse than no fare: it is quoted confidently and the user
    # has no way to tell. Nothing vague may produce a number.
    for q in ("how much is the ticket", "berapa harga tiket",
              "how much does it cost", "how much from here to there",
              "berapa tambang ke sana", "how much is parking"):
        assert fl.try_answer(q) is None, q


def test_exact_spelling_is_unaffected():
    a = fl.try_answer("Berapa tambang dari Kerinchi ke KLCC?")
    assert a and "RM2.90" in a
