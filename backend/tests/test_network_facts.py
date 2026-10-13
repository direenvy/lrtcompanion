"""
Structural-question tests — accessibility, lines at a station, interchanges.

These questions used to go through retrieval, where the answer is a paragraph
that happens to mention the station and the word "accessible". Now they are
answered from the GTFS feed and the accessibility overlay, so the tests assert
against the real data files rather than fixtures: if the overlay changes, these
should change with it, and a test that passed on a stale fixture would be
worse than no test.

Fully offline — no model, no database, no network.
"""
import pytest

import agents.network_facts as nf


# ── it answers the four shapes ───────────────────────────────────────────────

def test_station_wheelchair_question_is_answered():
    out = nf.try_answer("is KLCC wheelchair accessible?")
    assert out and "KLCC" in out
    assert "wheelchair-accessible" in out


def test_lines_at_an_interchange_are_listed():
    out = nf.try_answer("which lines stop at masjid jamek?")
    assert out
    for line in ("Ampang Line", "Kelana Jaya Line", "Sri Petaling Line"):
        assert line in out


def test_single_line_station_says_it_is_not_an_interchange():
    out = nf.try_answer("which lines serve wangsa maju?")
    assert out and "Kelana Jaya Line" in out
    assert "not an interchange" in out


def test_interchange_between_two_lines_is_named():
    out = nf.try_answer(
        "where do I change from the kelana jaya line to the ampang line?")
    assert out and "Masjid Jamek" in out


def test_lines_that_do_not_meet_say_so():
    """A real answer, not a failure: the Monorail and the BRT share no
    station, and inventing one would send someone to the wrong place."""
    out = nf.try_answer("where do i change between the monorail and the brt?")
    assert out and "do not share a station" in out


def test_line_audit_lists_the_stations():
    out = nf.try_answer("which stations on the monorail are not step-free?")
    assert out
    assert "11 of 11" in out
    assert "Bukit Bintang" in out


# ── it refuses to answer what it cannot ──────────────────────────────────────

def test_prose_questions_fall_through_to_rag():
    """The corpus is the right tool for these. Answering them from GTFS would
    be worse than retrieval, not better."""
    assert nf.try_answer("what should I do during a disruption?") is None
    assert nf.try_answer("how much is the my50 pass?") is None
    assert nf.try_answer("") is None


def test_a_question_naming_no_station_is_not_answered():
    """Resolving to the closest station in the network would state a fact
    about a place the user never mentioned."""
    assert nf.try_answer("is the station wheelchair accessible?") is None


def test_ktm_falls_through_because_it_is_not_in_the_feed():
    """KTM Komuter is absent from the GTFS feed this module reads. Answering
    about it would mean answering from no data at all."""
    out = nf.try_answer("where do i change between ktm and the monorail?")
    assert out is None


def test_line_mention_is_not_read_as_the_station_of_the_same_name():
    """'the Ampang line' is not Ampang station. Without this guard the audit
    question answered about one stop and reported it as the whole line — the
    same confusion the status board's detector has to handle."""
    out = nf.try_answer("which stations on the ampang line are not wheelchair accessible?")
    assert out and "of 18 stations" in out
    # ...while the station itself still resolves
    out = nf.try_answer("is ampang station wheelchair accessible?")
    assert out and "Ampang is recorded" in out


# ── honesty about the data ───────────────────────────────────────────────────

def test_unverified_is_never_reported_as_inaccessible(monkeypatch):
    """The overlay records yes / no / blank. Collapsing blank into "no"
    invents a barrier that was never surveyed, which for a wheelchair user is
    the error that matters."""
    real = nf._data()
    faked = {sid: dict(info) for sid, info in real.items()}
    target = next(sid for sid, i in faked.items() if i["name"].startswith("KLCC"))
    faked[target]["wheelchair"] = None
    monkeypatch.setattr(nf, "_data", lambda: faked)

    out = nf.try_answer("is KLCC wheelchair accessible?")
    assert out
    assert "has not been verified" in out
    assert "not recorded as inaccessible" in out


def test_line_uniform_data_is_declared_as_line_level():
    """The overlay currently holds one value per LINE, so an "all" or "none"
    answer is a line-level fact wearing a station-level shape. The answer has
    to say that, or it implies a per-station survey nobody did."""
    out = nf.try_answer("which stations on the monorail are not step-free?")
    assert "line-level fact" in out
    assert "not been assessed separately" in out


def test_interchange_platforms_are_reported_separately():
    """Masjid Jamek's KJ platform has no tactile path while its AG and PH
    platforms do. Averaging that into one verdict would be wrong in whichever
    direction it rounded."""
    out = nf.try_answer("does masjid jamek have tactile paving?")
    assert out and "differs by platform" in out
    assert "Kelana Jaya Line: not accessible" in out


def test_every_answer_carries_its_source():
    """An accessibility claim without its provenance is the claim an examiner
    will press on. The surveyed-not-guaranteed caveat travels with it."""
    for q in ("is KLCC wheelchair accessible?",
              "which stations on the monorail are not step-free?"):
        out = nf.try_answer(q)
        assert "oku_stations.csv" in out
        assert "not an operator guarantee" in out, q


# ── it never takes the chatbot down ──────────────────────────────────────────

def test_a_data_failure_falls_through_instead_of_raising(monkeypatch):
    def boom():
        raise FileNotFoundError("stops.txt")
    monkeypatch.setattr(nf, "_data", boom)
    assert nf.try_answer("is KLCC wheelchair accessible?") is None


def test_empty_feed_falls_through(monkeypatch):
    monkeypatch.setattr(nf, "_data", lambda: {})
    assert nf.try_answer("is KLCC wheelchair accessible?") is None


# ── acronyms survive the prettifier ──────────────────────────────────────────

@pytest.mark.parametrize("gtfs,want", [
    ("KLCC", "KLCC"),
    ("KL SENTRAL", "KL Sentral"),
    ("WANGSA MAJU", "Wangsa Maju"),
    ("IMBI", "Imbi"),
    ("PWTC", "PWTC"),
    ("KAMPUNG BARU - CBP COOPBANK PERTAMA", "Kampung Baru"),
])
def test_station_names_are_readable_without_mangling_acronyms(gtfs, want):
    assert nf._pretty(gtfs) == want


# ── the RAG pipeline consults it before retrieval ────────────────────────────

def test_rag_routes_structural_questions_here(monkeypatch):
    import agents.rag_agent as ra
    monkeypatch.setattr(ra, "_ensure_started", lambda: None)
    called = []
    monkeypatch.setattr(ra, "_embedding_retrieve",
                        lambda q, k: called.append(q) or [])
    out = _REAL_ANSWER("is KLCC wheelchair accessible?")
    assert out["mode"] == "network_facts"
    assert out["chunks_used"] == 0
    assert called == []                  # retrieval never ran


# conftest's no_rag_generation fixture replaces rag_agent.answer with a stub for
# the voice tests, so the real function has to be captured at import time —
# before any fixture runs. Looking it up inside the test would get the stub.
import agents.rag_agent as _ra            # noqa: E402
_REAL_ANSWER = _ra.answer
