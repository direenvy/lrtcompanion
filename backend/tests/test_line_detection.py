"""
Line attribution tests — station-name detection loaded from GTFS stops.txt
(offline; no network or DB involved).
"""
from api.dashboard import _detect_line, _detect_stations, _STATION_LINES


def test_station_table_loaded():
    assert len(_STATION_LINES) > 100    # 142 unique-line stations expected


def test_station_name_attributes_line_without_naming_it():
    assert _detect_line("stuck at wangsa maju for 20 minutes, no train") == "KJ"
    assert _detect_line("flood near johan setia station entrance") == "SA"
    assert _detect_line("train at taman connaught not moving") == "KGL"


def test_interchange_blocks_wrong_single_line_guess():
    # 'Ampang Park' serves KJ + MRT Putrajaya — it must NOT be attributed to
    # the Ampang line just because the word 'ampang' appears inside it
    assert _detect_line("doors stuck at ampang park") is None
    # plain 'ampang' still attributes to the Ampang line
    assert _detect_line("lrt ampang delayed again") == "AG"


def test_interchange_names_stay_unattributed():
    # Masjid Jamek serves KJ + AG + PH — a bare mention cannot pick one line
    assert _detect_line("crazy queue at masjid jamek") is None


def test_common_malay_words_do_not_match_stations():
    # 'kerjaya' (career) and 'cahaya' (light) are station names but also
    # ordinary words — they must never attribute a line by themselves
    assert _detect_line("peluang kerjaya dalam bidang cahaya dan damai") is None


def test_line_keywords_still_work():
    assert _detect_line("kelana jaya line completely down") == "KJ"
    assert _detect_line("lrt3 breakdown, shah alam line held") == "SA"


# ── Station-level detection (feeds automatic reroute avoidance) ──────────────

def test_named_station_resolves_to_stop_id():
    assert _detect_stations("train stuck at kampung baru, not moving") \
        == [("kampung baru", ["KJ11"])]


def test_sponsored_gtfs_name_matches_commuter_wording():
    # GTFS name is 'KAMPUNG BARU - CBP COOPBANK PERTAMA'; commuters say the base
    assert _detect_line("train stuck at kampung baru") == "KJ"


def test_interchange_blocks_every_platform():
    # Ampang Park serves KJ + Putrajaya — both platform stop_ids must block
    (name, stop_ids), = _detect_stations("doors jammed at ampang park")
    assert name == "ampang park"
    assert set(stop_ids) == {"KJ9", "PY20"}


def test_two_stations_in_one_report():
    found = dict(_detect_stations("stuck between kampung baru and dang wangi"))
    assert found == {"kampung baru": ["KJ11"], "dang wangi": ["KJ12"]}


def test_line_mention_does_not_block_the_station():
    # 'kelana jaya LINE' names the line, not Kelana Jaya station
    assert _detect_stations("kelana jaya line completely down") == []
    # but the station itself still blocks
    assert _detect_stations("big crowd at kelana jaya station") \
        == [("kelana jaya", ["KJ24"])]


def test_common_words_do_not_block_stations():
    assert _detect_stations("peluang kerjaya dalam bidang cahaya") == []


# ── Corroboration: one anonymous report must not reroute everyone ────────────

from api.dashboard import _derive_station_disruptions


def _alert(text, created_at="2026-07-12T10:10:00+00:00", source="user"):
    return {"text": text, "created_at": created_at, "source": source}


CUTOFF = "2026-07-12T10:00:00+00:00"


def test_single_report_is_advisory_not_blocking():
    blocked, advisory = _derive_station_disruptions(
        [_alert("train stuck at kampung baru")], CUTOFF)
    assert blocked == []
    assert len(advisory) == 1
    assert advisory[0]["name"] == "KAMPUNG BARU"
    assert advisory[0]["report_count"] == 1


def test_two_inapp_reports_corroborate_and_block():
    # two deliberate in-app reports (weight 1.0 each = 2.0) confirm and block
    blocked, advisory = _derive_station_disruptions([
        _alert("train stuck at kampung baru, doors jammed"),
        _alert("kampung baru platform packed, nothing moving"),
    ], CUTOFF)
    assert advisory == []
    assert len(blocked) == 1
    assert blocked[0]["name"] == "KAMPUNG BARU"
    assert blocked[0]["report_count"] == 2


def test_one_inapp_plus_one_tweet_is_advisory_not_blocked():
    # in-app (1.0) + one tweet (0.4) = 1.4 < 2.0 -> advisory, not auto-blocked
    blocked, advisory = _derive_station_disruptions([
        _alert("train stuck at kampung baru, doors jammed"),
        _alert("kampung baru platform packed", source="x_live"),
    ], CUTOFF)
    assert blocked == []
    assert len(advisory) == 1
    assert advisory[0]["name"] == "KAMPUNG BARU"


def test_same_text_spammed_counts_once():
    spam = "kampung baru is broken down!!"
    blocked, advisory = _derive_station_disruptions(
        [_alert(spam), _alert(spam), _alert("  ".join(spam.split()))], CUTOFF)
    assert blocked == []                      # 3 rows, 1 distinct message
    assert advisory[0]["report_count"] == 1


def test_old_reports_outside_window_ignored():
    blocked, advisory = _derive_station_disruptions([
        _alert("stuck at kampung baru", created_at="2026-07-12T09:00:00+00:00"),
        _alert("kampung baru not moving"),
    ], CUTOFF)
    assert blocked == []                      # only 1 in-window report
    assert advisory[0]["report_count"] == 1


# ── Official source: one authoritative announcement confirms alone ───────────

from api.dashboard import _source_weight, _signal_weight, CONFIRM_WEIGHT


def test_official_announcement_confirms_alone():
    # @AskRapidKL is authoritative — if they say a station is down, it's down
    blocked, advisory = _derive_station_disruptions(
        [_alert("Service disruption at kampung baru, trains held",
                source="x_official")], CUTOFF)
    assert advisory == []
    assert len(blocked) == 1
    assert blocked[0]["name"] == "KAMPUNG BARU"
    assert blocked[0]["corroboration"] >= CONFIRM_WEIGHT
    assert "x_official" in blocked[0]["sources"]


def test_source_weight_hierarchy():
    # official >= confirm threshold > in-app > anonymous tweet
    assert _source_weight("x_official") >= CONFIRM_WEIGHT
    assert _source_weight("user") == 1.0
    assert _source_weight("voice") == 1.0
    assert _source_weight("x_live") == 0.4
    assert _source_weight("something_unknown") == 0.4   # unknown = least trusted


def test_five_distinct_tweets_needed_without_official_or_inapp():
    # 4 tweets = 1.6 < 2.0 (advisory); the 5th crosses the threshold.
    # Genuinely different sentences, not one template numbered 0..3 — near
    # duplicates now merge into a single signal, which is the point of the rule.
    four = [
        _alert("kampung baru rosak lagi pagi ni", source="x_live"),
        _alert("stuck outside kampung baru, nothing moving", source="x_live"),
        _alert("why is kampung baru closed again", source="x_live"),
        _alert("no trains calling at kampung baru right now", source="x_live"),
    ]
    blocked, advisory = _derive_station_disruptions(four, CUTOFF)
    assert blocked == [] and len(advisory) == 1

    blocked, advisory = _derive_station_disruptions(
        four + [_alert("kampung baru still stuck now", source="x_live")], CUTOFF)
    assert advisory == [] and len(blocked) == 1


def test_official_outranks_duplicate_text_from_crowd():
    # same wording arriving from crowd AND official keeps the official weight
    txt = "kampung baru service disruption"
    w = _signal_weight({txt: "x_official"})
    assert w >= CONFIRM_WEIGHT
    assert _signal_weight({txt: "x_live"}) < CONFIRM_WEIGHT


# ── Interchange disruptions must appear in the feed (regression) ─────────────
# Masjid Jamek serves KJ+AG+PH, so _detect_line returns None. It must still be
# detected as a STATION and surfaced, or routing avoids it while the board
# silently hides it (the reported bug).

def test_interchange_has_no_line_but_is_detected_as_station():
    assert _detect_line("masjid jamek station down, huge crowd") is None
    stations = _detect_stations("masjid jamek station down, huge crowd")
    assert any(name == "masjid jamek" for name, _ in stations)


# ── Bare station → fan out to all lines it serves (regression) ────────────────
# The real-world case: "masjid jamek lrt down" names no line. The station is
# an interchange (KJ+AG+PH), so ALL three of those lines should be implicated
# (a broken platform breaks every line at that station), while lines that
# don't stop there (KGL/PYL/MR/BRT/SA) must stay untouched.

from api.dashboard import _lines_for_station_stops, _detect_stations


def test_bare_interchange_report_implicates_every_serving_line():
    stops = _detect_stations("masjid jamek lrt down")[0][1]   # ['AG7','KJ13','SP7']
    lines = _lines_for_station_stops(stops)
    assert lines == {"KJ", "AG", "PH"}


def test_bare_single_line_station_implicates_only_that_line():
    stops = _detect_stations("stuck at wangsa maju")[0][1]     # ['KJ4'] only
    lines = _lines_for_station_stops(stops)
    assert lines == {"KJ"}


def test_bare_multi_line_station_leaves_unrelated_lines_alone():
    stops = _detect_stations("masjid jamek lrt down")[0][1]
    lines = _lines_for_station_stops(stops)
    # Every non-serving line MUST NOT be implicated
    for other in ("KGL", "PYL", "MR", "BRT", "SA"):
        assert other not in lines


def test_short_station_name_upm_still_detected():
    # UPM is a real 3-char station (MRT Putrajaya). A bare len>=4 filter
    # silently excluded it — a report "upm down" produced no attribution
    # and no line lit up on the board (regression 12 Aug 2026).
    from api.dashboard import _detect_stations, _lines_for_station_stops
    st = _detect_stations("upm station not working")
    assert st and st[0][0] == "upm"
    assert "PYL" in _lines_for_station_stops(st[0][1])


# ── Fuzzy fallback for misspelled station names ──────────────────────────────
# Exact matching is why "masjid jamek stuck" works and "masjid jamik" does
# nothing — no chip, no fan-out, no reroute avoidance. These tests pin the four
# guards that make the fallback safe, because a false attribution here reddens
# a line and routes people away from a station that is running.

from api.dashboard import _fuzzy_detect_stations, STATION_FUZZY_THRESHOLD


def test_misspelled_station_is_detected():
    found = dict(_detect_stations("stuck at masjid jamik, no train coming"))
    assert "masjid jamek" in found


def test_transcription_error_is_detected():
    """The voice path returns phonetic spellings; they must still resolve."""
    found = dict(_detect_stations("kampong baru lrt rosak, semua terkandas"))
    assert "kampung baru" in found


def test_exact_match_wins_and_suppresses_the_fuzzy_pass(monkeypatch):
    """Guard 1. Text that works today must behave identically — the fuzzy pass
    does not even run, so it cannot reinterpret a correct report."""
    import api.dashboard as dash
    called = []
    monkeypatch.setattr(dash, "_fuzzy_detect_stations",
                        lambda t, **k: called.append(t) or [])
    assert dash._detect_stations("train stuck at kampung baru") \
        == [("kampung baru", ["KJ11"])]
    assert called == []


def test_no_fuzzy_matching_outside_a_disruption_context():
    """Guard 2. Idle chatter must never be fuzz-matched to a station."""
    assert _detect_stations("thinking about masjid jamik tomorrow") == []


def test_shorter_place_cannot_match_a_longer_station_name():
    """Guard 3, and the regression that motivated it: 'shah alam' is two words
    and STADIUM SHAH ALAM is three, so the span is never compared against it.
    This exact substitution reached a user once."""
    assert _detect_stations("shah alam traffic is terrible, jammed everywhere") == []


def test_ambiguous_match_yields_nothing(monkeypatch):
    """Guard 4. Two plausible stations is not a detection — guessing between
    them is worse than reporting neither, because the wrong one gets avoided.

    Built on a tie rather than hoping the real gazetteer contains one: both
    candidates score 92 against the span, inside AMBIGUITY_MARGIN."""
    import api.dashboard as dash
    monkeypatch.setattr(dash, "_STATION_NAMES", ["taman melati", "taman melatu"])
    monkeypatch.setattr(dash, "_STATION_STOP_IDS",
                        {"taman melati": ["KJ2"], "taman melatu": ["KJ3"]})
    assert dash._fuzzy_detect_stations("stuck at taman melatl", threshold=80) == []
    # ...while a clear winner is still returned
    monkeypatch.setattr(dash, "_STATION_NAMES", ["taman melati"])
    assert dash._fuzzy_detect_stations("stuck at taman melatl", threshold=80)         == [("taman melati", ["KJ2"])]


def test_common_word_stations_are_never_fuzzy_matched():
    """'universiti', 'merdeka' and friends are ordinary words. They already
    need a disruption context to match EXACTLY; fuzzy-matching them would
    undo that guard from the other side."""
    found = dict(_fuzzy_detect_stations("my universitti class is cancelled, broke down"))
    assert "universiti" not in found


def test_other_malaysian_places_do_not_resolve():
    """A threshold loose enough to catch typos must still reject places that
    are not stations. These are the negatives the threshold was tuned against."""
    for text in ("flight delayed at klia2 again, stuck",
                 "penang bridge closed this morning, jammed",
                 "jakarta mrt delayed this morning, stuck"):
        assert _fuzzy_detect_stations(text) == [], text


def test_threshold_is_the_measured_value():
    """82-88 satisfied both labelled sets (scripts/tune_station_fuzzy.py); 88
    is the highest, chosen because under-matching is the safer error. If this
    is ever lowered, re-run the script — 80 starts producing false matches."""
    assert STATION_FUZZY_THRESHOLD == 88


def test_fuzzy_matching_can_be_switched_off():
    """A kill switch that needs no deploy, because this is the one addition
    that is on by default."""
    import api.dashboard as dash
    assert dash.STATION_FUZZY is True


def test_a_line_mention_is_not_fuzzy_matched_to_its_station():
    """Guard 5, found by an existing test rather than by design.

    The exact pass REFUSES '<name> line' — it names the line, not the station.
    Guard 1 ("only run when exact matching found nothing") does not cover this,
    because a deliberate refusal and a genuine absence look identical from
    outside: the fuzzy pass then matched 'kelana jaya' at 100 and undid the
    guard. Both spellings must stay refused."""
    assert _detect_stations("kelana jaya line completely down") == []
    assert _detect_stations("kelana jaia line completely down") == []


# ── Off-network posts must not attribute a Rapid KL line ─────────────────────
# Measured, not hypothetical: of the 281 alert posts in the scraped log, five
# carried a false attribution because a post about ANOTHER network listed Rapid
# KL station names. Each was contributing 0.4 corroboration weight to a line
# that was running normally.

def test_ktm_disruption_does_not_redden_a_rapid_kl_line():
    """The real post: Subang Jaya and KL Sentral are both KTM stops AND Rapid
    KL stops, so a KTM breakdown was attributed to Kelana Jaya."""
    text = ("Another disruption hit the KTM line between Subang Jaya "
            "and KL Sentral stations")
    assert _detect_line(text) is None
    assert _detect_stations(text) == []


def test_road_traffic_bulletin_does_not_attribute_a_line():
    """Three real posts of this shape were attributed to the Ampang line,
    because a ROAD bulletin names stations as landmarks."""
    text = ("1901h: Trafik perlahan - KTM Serdang-Balakong - "
            "Sapura-The Mines-Balakong - Kuchai Link 2")
    assert _detect_line(text) is None
    assert _detect_stations(text) == []


def test_ets_and_komuter_are_off_network():
    assert _detect_line("Talian elektrik terputus, ETS dan KTM Komuter terganggu") is None
    assert _detect_line("Keretapi Tanah Melayu Berhad komuter delayed") is None


def test_an_explicit_line_overrides_the_off_network_guard():
    """A post can name both. 'LRT3 and KTM both down' really is about LRT3,
    and the guard must not swallow a genuine report to filter a foreign one."""
    assert _detect_line("LRT3 and KTM both down this morning") == "SA"
    assert _detect_line("trafik perlahan, ampang line pun rosak") == "AG"


def test_the_guard_does_not_touch_ordinary_reports():
    assert _detect_line("kelana jaya line down") == "KJ"
    assert _detect_line("stuck at kampung baru") == "KJ"
    assert _detect_stations("train stuck at kampung baru") \
        == [("kampung baru", ["KJ11"])]


# ── Fuzzy line-name matching ─────────────────────────────────────────────────

from api.dashboard import (_fuzzy_detect_line, LINE_FUZZY_THRESHOLD,
                           MIN_FUZZY_PHRASE_CHARS, _FUZZY_LINE_PHRASES)


def test_misspelled_line_name_attributes():
    assert _detect_line("kelana jaia line completely down") == "KJ"
    assert _detect_line("kajang lin delayed this morning") == "KGL"


def test_place_name_keywords_are_never_fuzzy_matched():
    """'ampang', 'kajang', 'putrajaya', 'shah alam' and 'sunway' are places.
    Fuzzy-matching a place name is how a report about a shopping trip reddens
    a line — and with only eight lines, a loose rule assigns one to almost
    any sentence."""
    fuzzed = {p for p, _lid in _FUZZY_LINE_PHRASES}
    for place in ("ampang", "kajang", "putrajaya", "shah alam", "sunway"):
        assert place not in fuzzed


def test_short_phrases_are_excluded_and_why():
    """'lrt3' is four characters, so at any threshold loose enough to catch
    'monorel' a bare 'lrt rosak lagi' scored high enough against it to redden
    LRT3 — on one of the commonest post shapes in the log. Character ratios
    are meaningless on short strings."""
    assert MIN_FUZZY_PHRASE_CHARS == 6
    assert all(len(p) >= MIN_FUZZY_PHRASE_CHARS for p, _lid in _FUZZY_LINE_PHRASES)
    for text in ("lrt rosak lagi", "lrt stuck again", "the lrt is down",
                 "mrt rosak pagi ni"):
        assert _fuzzy_detect_line(text) is None, text


def test_generic_complaints_do_not_reach_a_line():
    for text in ("train stuck everywhere this morning",
                 "stesen rosak, tak boleh masuk",
                 "my phone line is down",
                 "the queue line is so long, stuck for ages"):
        assert _fuzzy_detect_line(text) is None, text


def test_no_fuzzy_line_matching_outside_a_disruption_context():
    assert _detect_line("thinking about the kelana jaia line tomorrow") is None


def test_fuzzy_line_threshold_is_the_measured_value():
    """82: over the 281 real alert posts it adds nothing wrong, while 80 adds
    a false attribution (a KTM post reaching Kelana Jaya) and 86 adds nothing
    at all. Reproduce with:
        python scripts/tune_station_fuzzy.py --lines --real
    """
    assert LINE_FUZZY_THRESHOLD == 82
