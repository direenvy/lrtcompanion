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
