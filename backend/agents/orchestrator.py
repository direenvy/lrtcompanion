"""
Multi-Agent Orchestrator
Coordinates all three specialist agents into a single cohesive response.

Key design decisions:
- Rerouting ALWAYS runs when origin+destination are provided (not just on alert)
- RAG question is built from what the other two agents actually found
- Summary is a cohesive narrative, not 3 separate outputs stapled together
"""

import re
from agents.nlp_agent import predict as nlp_predict
from agents.rerouting_agent import reroute
from agents.rag_agent import answer as rag_answer

# Maps common line name mentions in text to GTFS route IDs
LINE_KEYWORDS = {
    "kelana jaya": "KJ", "kj line": "KJ",
    "ampang": "AG",
    "sri petaling": "PH",
    "kajang": "KGL", "mrt kajang": "KGL",
    "putrajaya": "PYL", "mrt putrajaya": "PYL",
    "monorail": "MR", "kl monorail": "MR",
    "brt": "BRT", "sunway": "BRT",
}


def _detect_line(text: str) -> str | None:
    """Extract the rail line mentioned in the report text."""
    lower = text.lower()
    for keyword, line_id in LINE_KEYWORDS.items():
        if keyword in lower:
            return line_id
    return None


def handle_full_disruption(
    text: str,
    origin: str,
    destination: str,
    disrupted_stops: list[str] | None = None,
) -> dict:
    """
    Full 3-agent pipeline:

    Agent 1 — NLP: classify the report (with Gemini fallback for low confidence)
    Agent 2 — Routing: ALWAYS compute best route when origin+destination given
    Agent 3 — RAG: retrieve advice that references what agents 1 & 2 found

    The summary ties all three together into one cohesive narrative.
    """

    # ── Agent 1: NLP ─────────────────────────────────────────────────────────
    nlp_result    = nlp_predict(text)
    sentiment     = nlp_result["sentiment"]
    issue_type    = nlp_result["issue_type"]
    is_disruption = nlp_result["disruption_alert"]
    nlp_method    = nlp_result.get("method", "local")

    # Detect line mentioned in text (even if NLP missed it)
    detected_line = _detect_line(text)

    # ── Agent 2: Rerouting ────────────────────────────────────────────────────
    # Always run when origin+destination are provided — don't gate on NLP alert
    reroute_result = None
    if origin and destination:
        reroute_result = reroute(
            origin.upper(), destination.upper(), disrupted_stops or []
        )

    # ── Agent 3: RAG ──────────────────────────────────────────────────────────
    # Build question informed by what agents 1 & 2 found
    route_context = ""
    if reroute_result and not reroute_result.get("error"):
        route_context = (
            f" The passenger needs to travel from {reroute_result['origin']} "
            f"to {reroute_result['destination']} "
            f"(~{reroute_result['estimated_minutes']} minutes, "
            f"{reroute_result['total_stops']} stops)."
        )

    if is_disruption:
        rag_question = (
            f"There is a reported {issue_type} on the LRT"
            + (f" ({detected_line} line)" if detected_line else "")
            + f".{route_context} "
            "What should affected passengers do? "
            "What are Rapid KL's official guidelines, compensation policies, "
            "and alternative transport options during a service disruption?"
        )
    elif sentiment == "negative":
        rag_question = (
            f"A passenger complained: \"{text[:180]}\".{route_context} "
            "What are Rapid KL's relevant passenger rights, "
            "complaint procedures, or service guidelines for this situation?"
        )
    else:
        rag_question = (
            f"Regarding Rapid KL LRT services: {text[:180]}{route_context} "
            "What relevant service information, fares, or guidelines apply?"
        )

    rag_result = rag_answer(rag_question, top_k=5)

    # ── Cohesive narrative summary ─────────────────────────────────────────────
    parts = []

    if is_disruption:
        line_str = f" on the {detected_line} line" if detected_line else ""
        parts.append(f"🚨 {issue_type.capitalize()} detected{line_str} ({sentiment} sentiment, via {nlp_method}).")
    else:
        parts.append(f"✅ No disruption detected — {sentiment} sentiment, classified as {issue_type}.")

    if reroute_result and not reroute_result.get("error"):
        steps = reroute_result.get("steps", [])
        transfers = reroute_result.get("interchanges", 0)
        transfer_str = f" with {transfers} transfer{'s' if transfers > 1 else ''}" if transfers else " direct"
        parts.append(
            f"Route from {reroute_result['origin']} → {reroute_result['destination']}: "
            f"~{reroute_result['estimated_minutes']} min{transfer_str}."
        )
        if disrupted_stops:
            avoided = reroute_result.get("disrupted_stops_avoided", [])
            if avoided:
                parts.append(f"Avoided {len(avoided)} disrupted stop(s).")
    elif origin and destination and reroute_result and reroute_result.get("error"):
        parts.append(f"Routing note: {reroute_result['error']}")
    elif not origin or not destination:
        parts.append("No origin/destination provided — routing skipped.")

    rag_ok = rag_result.get("answer", "").strip() and \
             "don't have" not in rag_result.get("answer", "").lower()
    if rag_ok:
        parts.append("Official Rapid KL advice retrieved below.")
    else:
        parts.append("No specific official advice found for this situation.")

    summary = " ".join(parts)

    return {
        "summary":          summary,
        "disruption_alert": is_disruption,
        "detected_line":    detected_line,
        "nlp":              nlp_result,
        "reroute":          reroute_result,
        "rag":              rag_result,
    }
