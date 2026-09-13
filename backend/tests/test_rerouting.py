import agents.rerouting_agent as ra
from agents.rerouting_agent import reroute, _find_stop_id, _load_gtfs


def test_gtfs_loads_full_network():
    stops, seq, names, edges = _load_gtfs()
    assert len(stops) == 187          # 8 lines incl. LRT3 Shah Alam
    assert "SA" in seq                # LRT3 present
    assert len(edges) > 300           # per-edge scheduled minutes (both directions)


def test_same_line_route():
    r = reroute("KLCC", "PUTRA HEIGHTS")
    assert "error" not in r
    assert r["origin"] == "KLCC"
    assert r["segments"][0]["line"] == "KJ"
    assert r["estimated_minutes"] > 0
    assert len(r["instructions"]) >= 2   # board + arrive


def test_cross_line_route_has_interchange():
    r = reroute("AMPANG", "GOMBAK")
    assert "error" not in r
    assert r["interchanges"] >= 1


def test_top3_routes_sorted_and_distinct():
    r = reroute("GOMBAK", "KAJANG")
    routes = r["routes"]
    assert 1 <= len(routes) <= 3
    mins = [rt["estimated_minutes"] for rt in routes]
    assert mins == sorted(mins)                       # best first
    seqs = [tuple(rt["lines_used"]) for rt in routes]
    assert len(seqs) == len(set(seqs))                # no cosmetic duplicates


def test_slow_alternatives_flagged_and_ranked_last():
    # >20-min-worse detours are kept as backups, but flagged and always last
    for o, d in [("KLCC", "AMPANG PARK"), ("GOMBAK", "KAJANG")]:
        routes = reroute(o, d)["routes"]
        assert "slow_option" not in routes[0]          # best is never flagged
        best_min = routes[0]["estimated_minutes"]
        for rt in routes[1:]:
            assert rt.get("slow_option", False) == \
                (rt["estimated_minutes"] - best_min > 20)
        flags = [bool(rt.get("slow_option")) for rt in routes]
        assert flags == sorted(flags)                  # slow ones come last


def test_fuzzy_typo_resolves():
    r = reroute("puchung prima", "kl sentral")
    assert "error" not in r
    assert r["origin"] == "PUCHONG PRIMA"
    assert r["query_corrected"] is True


def test_unknown_station_returns_suggestions():
    r = reroute("XYZNOWHERE", "KLCC")
    assert "error" in r
    assert r["bad_field"] == "origin"
    assert len(r["suggestions"]) == 3


def test_find_stop_id_returns_tuple():
    stops, _, _, _ = _load_gtfs()
    sid, name = _find_stop_id("KLCC", stops)
    assert sid and name == "KLCC"
    sid2, name2 = _find_stop_id("", stops)
    assert sid2 is None and name2 is None


def test_avoid_line_excluded_in_all_routes():
    # Masjid Jamek sits on multiple lines, so avoiding KJ stays routable
    r = reroute("MASJID JAMEK", "KAJANG", preferences={"avoid_lines": ["KJ"]})
    assert "error" not in r
    for rt in r["routes"]:
        assert "KJ" not in rt["lines_used"]


def test_avoiding_only_line_relaxes():
    # KLCC exists only on KJ — avoiding KJ must fail but offer the relaxed route
    r = reroute("KLCC", "PUTRA HEIGHTS", preferences={"avoid_lines": ["KJ"]})
    assert "error" in r
    assert r["relaxed_route"] is not None
    assert r["relaxed_route"]["estimated_minutes"] > 0


def test_disrupted_stop_not_in_path():
    base = reroute("KLCC", "PUTRA HEIGHTS")
    # pick a mid stop from the longest segment (first segment can be 1 stop)
    longest = max(base["segments"], key=lambda seg: len(seg["station_points"]))
    mid_stop = longest["station_points"][len(longest["station_points"]) // 2]["stop_id"]
    r = reroute("KLCC", "PUTRA HEIGHTS", disrupted_stops=[mid_stop])
    if "error" not in r:
        all_ids = [p["stop_id"] for s in r["segments"] for p in s["station_points"]]
        assert mid_stop not in all_ids
    else:
        assert "alternatives" in r    # no-path fallback contract


def test_fewest_stops_not_worse_on_stop_count():
    fast = reroute("GOMBAK", "KAJANG", preferences={"priority": "fastest"})
    few = reroute("GOMBAK", "KAJANG", preferences={"priority": "fewest_stops"})
    assert few["total_stops"] <= fast["total_stops"]


def test_named_interchanges_connect():
    # Glenmarie (KJ) <-> Glenmarie 2 (SA) differ by name; BRT's USJ7 lacks a space
    r = reroute("KLCC", "STADIUM SHAH ALAM")
    assert "error" not in r
    assert "SA" in r["routes"][0]["lines_used"] or any(
        "SA" in rt["lines_used"] for rt in r["routes"])
    r2 = reroute("SUNWAY LAGOON", "KLCC")
    assert "error" not in r2          # BRT is not an island


def test_any_blocked_mid_station_is_bypassed_network_wide():
    """Property sweep: for seeded random O-D pairs across the whole network,
    blocking a station mid-route must yield either a route that avoids it and
    still reaches the destination, or an honest no-path with alternatives."""
    import random
    stops, *_ = _load_gtfs()
    names = sorted({s["name"] for s in stops.values()})
    rng = random.Random(42)

    checked = 0
    while checked < 12:
        o, d = rng.sample(names, 2)
        base = reroute(o, d)
        if base.get("error"):
            continue
        points = [p for seg in base["segments"] for p in seg["station_points"]]
        mids = points[1:-1]
        if not mids:
            continue
        block_name = mids[len(mids) // 2]["name"]
        block_ids = [sid for sid, s in stops.items() if s["name"] == block_name]
        r = reroute(o, d, disrupted_stops=block_ids)
        if r.get("error"):
            assert "alternatives" in r          # no-path fallback contract
        else:
            new_ids = [p["stop_id"] for seg in r["segments"]
                       for p in seg["station_points"]]
            assert not set(block_ids) & set(new_ids)
            assert r["destination"] == base["destination"]
        checked += 1


def test_disrupted_stop_ids_case_insensitive():
    # users type lowercase; GTFS ids are uppercase — must still block
    r = reroute("CHOW KIT", "IMBI", disrupted_stops=[" mr8 "])
    assert "error" not in r
    ids = [p["stop_id"] for s in r["segments"] for p in s["station_points"]]
    assert "MR8" not in ids
    assert r["disrupted_stops_avoided"] == ["MR8"]


def test_disrupted_stops_accept_station_names():
    # typing a station name (any case) blocks it — incl. sponsored GTFS names
    r = reroute("CHOW KIT", "IMBI", disrupted_stops=["bukit nanas"])
    ids = [p["stop_id"] for s in r["segments"] for p in s["station_points"]]
    assert "MR8" not in ids
    r2 = reroute("KLCC", "MASJID JAMEK", disrupted_stops=["kampung baru"])
    ids2 = [p["stop_id"] for s in r2["segments"] for p in s["station_points"]]
    assert "KJ11" not in ids2


def test_disrupted_points_returned_for_map():
    # the map needs coordinates of avoided stations to render red markers
    r = reroute("CHOW KIT", "IMBI", disrupted_stops=["MR8"])
    pts = r["disrupted_points"]
    assert len(pts) == 1
    assert pts[0]["stop_id"] == "MR8"
    assert pts[0]["name"] == "BUKIT NANAS"
    assert isinstance(pts[0]["lat"], float) and isinstance(pts[0]["lon"], float)
    # interchange blocked by name -> multiple platforms, ONE deduped marker
    r2 = reroute("SENTUL", "CHAN SOW LIN", disrupted_stops=["plaza rakyat"])
    assert len(r2["disrupted_points"]) == 1
    assert r2["disrupted_points"][0]["name"] == "PLAZA RAKYAT"


def test_route_through_disruption_demoted_to_last():
    # the normal route stays visible when a station on it is disrupted —
    # flagged, ranked last; the detour takes the top spot
    r = reroute("CHOW KIT", "IMBI", disrupted_stops=["MR8"])
    routes = r["routes"]
    assert not routes[0].get("through_disruption")       # best = detour
    last = routes[-1]
    assert last["through_disruption"] is True
    assert last["lines_used"] == ["MR"]                  # the original direct route
    ids = [p["stop_id"] for s in last["segments"] for p in s["station_points"]]
    assert "MR8" in ids                                  # genuinely passes through
    # blocking a station NOT on the normal path adds no through-route
    r2 = reroute("PUTRA HEIGHTS", "USJ 7", disrupted_stops=["KJ30"])
    assert not any(rt.get("through_disruption") for rt in r2["routes"])


def test_through_disruption_route_reports_real_walking_time():
    # The through-route is copied field-by-field from the undisrupted result.
    # Omitting transfer_minutes made walk_minutes fall back to 0, so a route
    # with an interchange advertised "0 min walk".
    r = reroute("16 SIERRA", "KELANA JAYA", disrupted_stops=["AG7", "KJ13", "SP7"])
    through = next(rt for rt in r["routes"] if rt.get("through_disruption"))
    assert through["interchanges"] >= 1
    assert through["transfer_minutes"] > 0
    assert through["walk_minutes"] > 0
    assert "exposed_transfers" in through


def test_walking_cap_never_promotes_the_disrupted_route():
    # A cap tighter than every detour must NOT fall through to the route that
    # passes through the confirmed-disrupted station — it stays demoted, and
    # the user is told the cap could not be met instead.
    for origin, dest in (("16 SIERRA", "KELANA JAYA"),
                         ("KLCC", "HANG TUAH"),
                         ("KELANA JAYA", "PUDU")):
        r = reroute(origin, dest, disrupted_stops=["AG7", "KJ13", "SP7"],
                    preferences={"max_walk_minutes": 5})
        assert not r["routes"][0].get("through_disruption"), origin
        assert r["walking_note"]["reason"] == "over_cap"
        # the option is still offered, just never first
        assert any(rt.get("through_disruption") for rt in r["routes"])


def test_unresolvable_disrupted_tokens_reported_not_silently_avoided():
    r = reroute("KOTA DAMANSARA", "BUKIT BINTANG",
                disrupted_stops=["KG 15", "muzium negra"])
    assert r["disrupted_unresolved"] == ["KG 15", "MUZIUM NEGRA"]
    assert r["disrupted_stops_avoided"] == []      # nothing fake in the badge
    assert r["lines_used"] == ["KGL"]              # unblocked direct route
    # the correct spellings DO block and force the detour
    r2 = reroute("KOTA DAMANSARA", "BUKIT BINTANG", disrupted_stops=["KG15"])
    assert r2["disrupted_unresolved"] == []
    assert r2["lines_used"] != ["KGL"] or r2["routes"][0].get("through_disruption") is None
    ids = [p["stop_id"] for s in r2["segments"] for p in s["station_points"]]
    assert "KG15" not in ids


def test_network_map_endpoint_returns_all_lines_ordered():
    from api.rerouting import network_map
    out = network_map()
    assert out["line_count"] == 8
    assert out["station_count"] == 187
    # each line's stations carry coordinates and are non-empty
    for line in out["lines"]:
        assert line["stations"]
        s0 = line["stations"][0]
        assert isinstance(s0["lat"], float) and isinstance(s0["lon"], float)
    # LRT3 present with its known endpoints in order
    sa = next(l for l in out["lines"] if l["line_id"] == "SA")
    assert sa["stations"][0]["name"] == "BANDAR UTAMA"
    assert sa["stations"][-1]["name"] == "JOHAN SETIA"


# ── prefer_shelter: interchange-shelter routing (survey CSV = source of truth) ──

def test_exposed_set_loaded_from_csv():
    assert ra._norm_station("BUKIT BINTANG") in ra._EXPOSED_INTERCHANGES
    assert ra._norm_station("BANDAR UTAMA") not in ra._EXPOSED_INTERCHANGES


def test_exposed_interchange_penalised_under_shelter():
    stops, seq, _names, emin = _load_gtfs()
    g_plain = ra._build_graph(stops, seq, preferences={"prefer_shelter": False}, edge_minutes=emin)
    g_shelt = ra._build_graph(stops, seq, preferences={"prefer_shelter": True},  edge_minutes=emin)
    def bb_edge(g):
        for u, v, d in g.edges(data=True):
            if d.get("route_id") == "INTERCHANGE" and d.get("exposed")                and g.nodes[u].get("name","").strip() == "BUKIT BINTANG":
                return d["weight"]
        return None
    w_plain, w_shelt = bb_edge(g_plain), bb_edge(g_shelt)
    assert w_plain is not None and w_shelt is not None
    assert w_shelt == w_plain + ra.INTERCHANGE_EXPOSED_PENALTY


def test_covered_interchange_never_flagged_exposed():
    stops, seq, _names, emin = _load_gtfs()
    g = ra._build_graph(stops, seq, preferences={"prefer_shelter": True}, edge_minutes=emin)
    covered_names = {"BANDAR UTAMA", "GLENMARIE", "GLENMARIE 2", "PASAR SENI",
                     "KL SENTRAL", "AMPANG PARK", "MALURI"}
    for u, v, d in g.edges(data=True):
        if d.get("route_id") == "INTERCHANGE" and d.get("exposed"):
            assert g.nodes[u].get("name","").strip() not in covered_names


def test_shelter_note_absent_without_shelter():
    off = reroute("TUN RAZAK EXCHANGE", "IMBI", preferences={"prefer_shelter": False})
    assert off.get("shelter_note") is None


# ── Station aliases / initialisms (TRX etc.) ─────────────────────────────────

def test_trx_alias_resolves_to_tun_razak_exchange():
    stops, *_ = _load_gtfs()
    sid, name = ra._find_stop_id("TRX", stops)
    assert name == "TUN RAZAK EXCHANGE"


def test_alias_route_matches_full_name_route():
    # "TRX" must behave identically to the full station name — same route,
    # same shelter warning (this was the reported inconsistency).
    a = reroute("TRX", "IMBI", preferences={"prefer_shelter": True})
    b = reroute("TUN RAZAK EXCHANGE", "IMBI", preferences={"prefer_shelter": True})
    assert a.get("lines_used") == b.get("lines_used")
    assert bool(a.get("shelter_note")) == bool(b.get("shelter_note"))


def test_all_aliases_target_real_stations():
    stops, *_ = _load_gtfs()
    names = {i["name"].upper().strip() for i in stops.values()}
    for alias, target in ra._STATION_ALIASES.items():
        assert target.upper().strip() in names, f"{alias} -> {target} not in GTFS"


# ── Walk-safety survey (prefer_safer_walk) ───────────────────────────────────
# The underlying CSV is an observational Street View survey, so these tests pin
# the RUBRIC and the opt-in behaviour, never specific stations' ratings.

def test_walk_safety_survey_loaded():
    assert len(ra._WALK_SAFETY) >= 150
    for entry in ra._WALK_SAFETY.values():
        assert 0 <= entry["score"] <= 5
        assert entry["level"] in {"good", "medium", "bad"}
        assert len(entry["failing"]) == 5 - entry["score"]


def test_walk_safety_level_boundaries():
    for entry in ra._WALK_SAFETY.values():
        if entry["score"] >= ra.WALK_SAFETY_GOOD_MIN:
            assert entry["level"] == "good"
        elif entry["score"] >= ra.WALK_SAFETY_MEDIUM_MIN:
            assert entry["level"] == "medium"
        else:
            assert entry["level"] == "bad"


def test_walk_safety_note_requires_opt_in():
    bad = next(n for n, e in ra._WALK_SAFETY.items() if e["level"] == "bad")
    assert ra._build_safety_note({"prefer_safer_walk": False}, bad, bad) is None
    assert ra._build_safety_note({}, bad, bad) is None


def test_walk_safety_note_fires_for_low_score():
    bad = next(n for n, e in ra._WALK_SAFETY.items() if e["level"] == "bad")
    note = ra._build_safety_note({"prefer_safer_walk": True}, bad, bad)
    assert note is not None
    assert note["level"] == "bad"
    assert note["reason"] == "walk_safety"
    # honest framing must survive refactors — it is the reason this is advisory
    assert "not a" in note["message"].lower()


def test_walk_safety_note_absent_when_both_endpoints_good():
    good = [n for n, e in ra._WALK_SAFETY.items() if e["level"] == "good"][:2]
    assert ra._build_safety_note({"prefer_safer_walk": True}, *good) is None


def test_walk_safety_note_names_only_the_failing_endpoint():
    bad  = next(n for n, e in ra._WALK_SAFETY.items() if e["level"] == "bad")
    good = next(n for n, e in ra._WALK_SAFETY.items() if e["level"] == "good")
    note = ra._build_safety_note({"prefer_safer_walk": True}, bad, good)
    assert [s["role"] for s in note["stations"]] == ["origin"]


def test_walk_safety_interchange_keeps_worse_rating():
    # USJ 7 is surveyed twice (KJ31 and BRT07) and the two rows disagree.
    # A safety warning must not be softened by CSV row order.
    entry = ra._WALK_SAFETY.get("USJ7")
    assert entry is not None and entry["score"] == 3


def test_walk_safety_does_not_change_routing():
    on  = reroute("KERINCHI", "KLCC", preferences={"prefer_safer_walk": True})
    off = reroute("KERINCHI", "KLCC", preferences={"prefer_safer_walk": False})
    assert on["estimated_minutes"] == off["estimated_minutes"]
    assert on.get("lines_used") == off.get("lines_used")
    assert on.get("safety_note") is not None
    assert off.get("safety_note") is None
