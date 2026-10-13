"""
Deterministic answers to structural questions about the network.

The RAG chatbot retrieves prose from 41 Prasarana documents. That is the right
tool for "what should I do during a disruption", and the wrong tool for "is
KLCC wheelchair accessible" — the answer to the second is a cell in a CSV, and
retrieving a paragraph that happens to mention KLCC and accessibility is how a
confident wrong answer gets produced.

This module answers that second kind of question from the structured data the
routing agent already loads: GTFS stops, the 187-row accessibility overlay,
and the line each platform belongs to. Same contract and same place in the
pipeline as the fare bypass — `try_answer` returns a string or None, and
`rag_agent.answer` consults it before retrieval. No model is involved, so
there is nothing to verify and nothing to hallucinate.

It handles four shapes:

  accessibility   "is KLCC wheelchair accessible?"
                  "does Masjid Jamek have tactile paving?"
  lines at a stop "which lines stop at Masjid Jamek?"
  interchanges    "where do I change from Kelana Jaya to the Ampang line?"
  line audit      "which stations on the Ampang line are not step-free?"

The unverified case is reported as unverified, never as "no". The overlay
distinguishes yes / no / blank, and collapsing blank into no would invent a
barrier that was never surveyed — which for a wheelchair user is the error
that matters.
"""

import re

# Line codes as commuters name them. Shared with the dashboard's LINE_META
# vocabulary, but kept local: this module must answer when the dashboard is
# unavailable, and the two lists are allowed to drift for different reasons.
LINE_WORDS: dict[str, tuple[str, ...]] = {
    "KJ":  ("kelana jaya", "kj line", "lrt kelana jaya"),
    "AG":  ("ampang line", "lrt ampang"),
    "PH":  ("sri petaling", "sri petaling line"),
    "KGL": ("mrt kajang", "kajang line", "kajang"),
    "PYL": ("mrt putrajaya", "putrajaya line", "putrajaya"),
    "MR":  ("monorail", "kl monorail"),
    "BRT": ("brt", "brt sunway", "sunway line"),
    "SA":  ("lrt3", "shah alam line", "lrt 3"),
}
# KTM Komuter is deliberately absent: it is not in the GTFS feed this module
# reads, so every answer about it would be drawn from no data at all. A
# question about KTM falls through to RAG, where the corpus may cover it.

LINE_LABEL = {
    "KJ": "Kelana Jaya Line", "AG": "Ampang Line",
    "PH": "Sri Petaling Line", "KGL": "MRT Kajang Line",
    "PYL": "MRT Putrajaya Line", "MR": "KL Monorail",
    "BRT": "BRT Sunway Line", "SA": "LRT3 Shah Alam Line",
}

WHEELCHAIR_WORDS = ("wheelchair", "step free", "step-free", "stepfree",
                    "oku", "lift", "accessible", "accessibility",
                    "kerusi roda")
TACTILE_WORDS = ("tactile", "blind", "visually impaired", "guiding path",
                 "braille", "tunanetra", "buta")
LINES_AT_WORDS = ("which line", "what line", "which lines", "what lines",
                  "lines stop", "lines serve", "lines at", "laluan mana")
INTERCHANGE_WORDS = ("interchange", "change from", "change between",
                     "transfer from", "transfer between", "switch from",
                     "connect", "bertukar")
NEGATIVE_WORDS = ("not ", "no ", "without", "lack", "missing", "tidak",
                  "tanpa", "which stations are not")

# A station name must match this closely to be used. Higher than the routing
# resolver's cutoff on purpose: routing can offer "did you mean", while a
# chatbot answer that silently resolves to the wrong station states a fact
# about a place the user never asked about.
NAME_SCORE_CUTOFF = 90


def _data():
    """GTFS stops + accessibility overlay, loaded by the routing agent.

    Imported lazily so this module costs nothing until a question needs it,
    and so a GTFS problem surfaces as "no answer" rather than an import error
    that takes the chatbot down.
    """
    from agents.rerouting_agent import _load_gtfs
    stops, _seq, _names, _mins = _load_gtfs()
    return stops


def _by_name(stops: dict) -> dict[str, list[str]]:
    """Station name -> every platform stop_id with that name (interchanges)."""
    out: dict[str, list[str]] = {}
    for sid, info in stops.items():
        out.setdefault(info["name"].upper().strip(), []).append(sid)
    return out


def _resolve_name(question: str, names: list[str]) -> str | None:
    """The one station named in the question, or None.

    Longest name first, so "ampang park" is never read as "ampang". Only an
    exact span match counts — a question that names no station must produce
    no answer rather than the closest station in the network.
    """
    q = " ".join(question.upper().split())
    for name in sorted(names, key=len, reverse=True):
        # The GTFS name may be sponsored ("KAMPUNG BARU - CBP COOPBANK
        # PERTAMA"); commuters write the base, so match on that too.
        for variant in {name, name.split(" - ")[0].strip()}:
            if len(variant) < 4:
                continue
            # '<name> LINE' names the line, not the station. Without this,
            # "which stations on the Ampang line are not step-free" resolves
            # to Ampang STATION and answers about one stop instead of
            # auditing the line — the same confusion the status board's
            # detector has to guard against.
            if re.search(r"\b" + re.escape(variant) + r"\b(?!\s+LINE\b)", q):
                return name
    return None


def _lines_of(stop_ids: list[str], stops: dict) -> list[str]:
    seen, out = set(), []
    for sid in stop_ids:
        rid = stops[sid].get("route_id") or ""
        rid = {"MRT": "KGL"}.get(rid, rid)
        if rid and rid not in seen:
            seen.add(rid)
            out.append(rid)
    return out


# Tokens that are acronyms, not words, and must not be title-cased into
# "Klcc" / "Kl Sentral". Taken from the actual GTFS name list, which is closed
# — 162 names — so an explicit set is accurate rather than a heuristic that
# would mangle IMBI or UDA. Extend it if the feed gains a station.
_ACRONYMS = {"KL", "KLCC", "PWTC", "USJ", "USJ7", "UPM", "UITM", "UOB",
             "IOI", "CBP", "SS", "TRX", "UKM", "UM", "BRT", "KTM", "SA",
             "DR", "LRT", "MRT"}


def _pretty(gtfs_name: str) -> str:
    """Human-readable station name from the upper-case GTFS form."""
    base = gtfs_name.split(" - ")[0].strip()
    return " ".join(t if t.upper() in _ACRONYMS else t.title()
                    for t in base.split())


def _label(code: str) -> str:
    return LINE_LABEL.get(code, code)


def _lines_in_question(question: str) -> list[str]:
    """Line codes named in the question, in the order they appear."""
    q = question.lower()
    hits: list[tuple[int, str]] = []
    for code, words in LINE_WORDS.items():
        best = min((q.find(w) for w in words if w in q), default=-1)
        if best >= 0:
            hits.append((best, code))
    return [c for _pos, c in sorted(hits)]


def _access_phrase(value, kind: str, station: str) -> str:
    """One sentence about a yes / no / unverified accessibility value."""
    if value is True:
        return (f"**Yes — {station} is recorded as {kind}-accessible.**"
                if kind == "wheelchair"
                else f"**Yes — {station} has a tactile guiding path recorded "
                     f"as continuous to outside the station.**")
    if value is False:
        return (f"**No — {station} is recorded as NOT {kind}-accessible.**"
                if kind == "wheelchair"
                else f"**No — {station} has no recorded tactile guiding path "
                     f"continuous to outside the station.**")
    # None: surveyed set does not cover this station.
    return (f"**{station} has not been verified for {kind} access.** "
            "It is not recorded as inaccessible — it is simply not in the "
            "surveyed set, and I will not guess either way.")


SOURCE_NOTE = ("Source: the project's accessibility overlay "
               "(`data/raw/accessibility/oku_stations.csv`), compiled from "
               "Rapid KL's PULSE listings and map imagery. An observational "
               "record, not an operator guarantee — a lift can be out of "
               "service on the day.")


def _answer_accessibility(question: str, stops: dict,
                          by_name: dict[str, list[str]]) -> str | None:
    ql = question.lower()
    wants_tactile = any(w in ql for w in TACTILE_WORDS)
    wants_chair = any(w in ql for w in WHEELCHAIR_WORDS)
    if not (wants_tactile or wants_chair):
        return None

    station = _resolve_name(question, list(by_name))
    if not station:
        return None

    ids = by_name[station]
    lines = _lines_of(ids, stops)
    base = _pretty(station)

    parts = []
    for kind, wanted in (("wheelchair", wants_chair), ("tactile", wants_tactile)):
        if not wanted:
            continue
        # An interchange has several platforms and they can differ. Report the
        # per-platform split rather than averaging it away: "accessible" is
        # not a property of a station if one of its platforms is not.
        values = {sid: stops[sid].get(kind) for sid in ids}
        distinct = set(values.values())
        if len(distinct) == 1:
            parts.append(_access_phrase(distinct.pop(), kind, base))
        else:
            parts.append(f"**{base} differs by platform for {kind} access:**")
            for sid, val in values.items():
                code = _lines_of([sid], stops)
                state = ("accessible" if val is True else
                         "not accessible" if val is False else "unverified")
                parts.append(f"- {_label(code[0]) if code else sid}: {state}")

    if lines:
        parts.append("Lines served: " + ", ".join(_label(c) for c in lines) + ".")
    parts.append(SOURCE_NOTE)
    return "\n\n".join(parts)


def _answer_lines_at(question: str, stops: dict,
                     by_name: dict[str, list[str]]) -> str | None:
    ql = question.lower()
    if not any(w in ql for w in LINES_AT_WORDS):
        return None
    station = _resolve_name(question, list(by_name))
    if not station:
        return None
    lines = _lines_of(by_name[station], stops)
    base = _pretty(station)
    if not lines:
        return None
    if len(lines) == 1:
        return (f"**{base} is served by one line: {_label(lines[0])}.** "
                "It is not an interchange.")
    return (f"**{base} is an interchange served by {len(lines)} lines:** "
            + ", ".join(_label(c) for c in lines) + ".\n\n"
            "A disruption at this station therefore affects every one of them, "
            "which is why a report naming it turns all of those lines red on "
            "the status board.")


def _answer_interchange(question: str, stops: dict,
                        by_name: dict[str, list[str]]) -> str | None:
    ql = question.lower()
    if not any(w in ql for w in INTERCHANGE_WORDS):
        return None
    codes = _lines_in_question(question)
    if len(codes) < 2:
        return None
    a, b = codes[0], codes[1]

    shared = [name for name, ids in by_name.items()
              if {a, b} <= set(_lines_of(ids, stops))]
    if not shared:
        # A real and useful answer: not every pair of lines touches.
        return (f"**The {_label(a)} and the {_label(b)} do not share a "
                f"station.** Changing between them needs a third line, so ask "
                "for a route between two specific stations instead and the "
                "planner will work out the transfers.")
    pretty = sorted(_pretty(n) for n in shared)
    if len(pretty) == 1:
        return (f"**Change between the {_label(a)} and the {_label(b)} at "
                f"{pretty[0]}.** It is the only station the two lines share, "
                "so a disruption there removes the connection entirely.")
    return (f"**The {_label(a)} and the {_label(b)} connect at "
            f"{len(pretty)} stations:** " + ", ".join(pretty) + ".")


def _answer_line_audit(question: str, stops: dict,
                       by_name: dict[str, list[str]]) -> str | None:
    """'which stations on the Ampang line are not wheelchair accessible?'"""
    ql = question.lower()
    wants_tactile = any(w in ql for w in TACTILE_WORDS)
    wants_chair = any(w in ql for w in WHEELCHAIR_WORDS)
    if not (wants_tactile or wants_chair):
        return None
    if "station" not in ql:
        return None
    codes = _lines_in_question(question)
    if len(codes) != 1:
        return None
    # Only when no single station is named — otherwise the per-station answer
    # above is the better one and already ran.
    if _resolve_name(question, list(by_name)):
        return None

    code = codes[0]
    kind = "tactile" if wants_tactile else "wheelchair"
    negative = any(w in ql for w in NEGATIVE_WORDS)

    on_line = [(sid, info) for sid, info in stops.items()
               if {"MRT": "KGL"}.get(info.get("route_id"), info.get("route_id")) == code]
    if not on_line:
        return None

    want = False if negative else True
    names = sorted({_pretty(info["name"])
                    for sid, info in on_line if info.get(kind) is want})
    unverified = sorted({_pretty(info["name"])
                         for sid, info in on_line if info.get(kind) is None})

    word = ("without a recorded tactile path" if (wants_tactile and negative)
            else "with a recorded tactile path" if wants_tactile
            else "NOT recorded as step-free" if negative
            else "recorded as step-free")

    total = len({i["name"] for _s, i in on_line})
    out = [f"**{len(names)} of {total} stations "
           f"on the {_label(code)} are {word}.**"]
    out.append(", ".join(names) if names else "None.")

    # Honesty check computed from the data, not assumed: the overlay currently
    # records one value per LINE, so "all" and "none" answers are line-level
    # facts wearing a station-level shape. Saying so is the difference between
    # a true statement and an implied per-station survey that was never done.
    values = {info.get(kind) for _s, info in on_line}
    if len(values) == 1:
        out.append(f"Every station on this line carries the same recorded "
                   f"{kind} value, so this is a line-level fact rather than a "
                   f"per-station survey result. Individual stations on the "
                   f"line have not been assessed separately.")
    if unverified:
        out.append(f"{len(unverified)} station(s) on this line are unverified "
                   f"for {kind} access and are counted in neither group: "
                   + ", ".join(unverified) + ".")
    out.append(SOURCE_NOTE)
    return "\n\n".join(out)


def try_answer(question: str) -> str | None:
    """A deterministic structural answer, or None to fall through to RAG.

    Never raises: a missing GTFS file or an unreadable overlay returns None,
    and the chatbot answers the question the way it does today.
    """
    if not (question or "").strip():
        return None
    try:
        stops = _data()
        if not stops:
            return None
        by_name = _by_name(stops)
        for handler in (_answer_accessibility, _answer_lines_at,
                        _answer_interchange, _answer_line_audit):
            out = handler(question, stops, by_name)
            if out:
                return out
    except Exception as e:
        print(f"[Facts] structural lookup unavailable ({type(e).__name__})")
    return None
