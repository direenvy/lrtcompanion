"""
Intent gate — does a scraped post actually REPORT a live service problem?

The classifier answers "is this negative, and what kind of issue is it about".
It never asks the prior question: is the author reporting something happening
to them now, or talking about the railway? Those are different things, and the
log shows the difference costing real corroboration weight:

    "lrt kj rosak sebab loke letak jawatan ke"      (a political joke)
    "i pejuang lrt kelana jaya line 😂"             (a loyalty joke)
    "LRT3 delayed, contractor kecil angry"          (a news summary)

Each is negative, each names a Rapid KL line, each raised an alert, and each
contributed 0.4 to the corroboration of a line that was running normally. Five
such posts confirm a disruption that never happened. The same root cause made
the voice assistant log "I want to go to Mid Valley" as a breakdown.

This asks one language-model question per post that would otherwise raise an
alert, and clears the alert flag when the answer is no. The post is still
logged and still appears on the live feed — nothing is hidden from the user —
it simply stops voting.

Design rules, deliberately the same as the RAG grounding verifier:

  FAILS OPEN   a timeout, a quota error or an unreadable reply keeps the alert.
               Missing a real disruption is worse than counting a joke, so
               every uncertain case resolves towards keeping the signal.
  OFF BY DEFAULT   set INTENT_GATE=1 to enable. It adds a network call to the
               ingestion path and it changes how much evidence a confirmation
               needs; neither should happen because a module was imported.
  OFFICIAL POSTS SKIP IT   an @AskRapidKL announcement is authoritative. There
               is nothing to second-guess and no call worth spending.

Enable with:
    INTENT_GATE=1                      # off unless set
    INTENT_GATE_PROVIDER=gemini|groq   # which provider to try first
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

INTENT_GATE = os.getenv("INTENT_GATE", "0").strip() == "1"
GATE_PROVIDER = os.getenv("INTENT_GATE_PROVIDER", "gemini").strip().lower()
GATE_TIMEOUT_SECONDS = 6
# The voice turn is interactive — the user is waiting while it answers. The
# Gemini classifier refinement was already removed from that path because it
# cost ~9 s. A shorter budget keeps the gate from reintroducing the same
# problem: if it has not answered in this long, fail open and route the user.
VOICE_TIMEOUT_SECONDS = 3

PROMPT = """You are filtering social media posts for a rail disruption monitor \
covering the Klang Valley (Kuala Lumpur) rail network: LRT Kelana Jaya, LRT \
Ampang/Sri Petaling, LRT3 Shah Alam, MRT Kajang, MRT Putrajaya, KL Monorail, \
KTM Komuter and the BRT.

Decide whether the post REPORTS A SERVICE PROBLEM THAT IS HAPPENING NOW on \
that network.

Reply with ONLY valid JSON: {{"live": true|false, "why": "<6 words or less>"}}

live = true when the author is describing a problem they or others are \
experiencing right now: a breakdown, a delay, a stoppage, overcrowding, a \
closure, a power or signalling fault, a service announcement about a current \
disruption.

live = false when the post is:
  - a joke, meme, insult or sarcasm that merely mentions a train or line
  - political commentary, or a complaint about policy, funding or management
  - a news article, press summary, or a report about future or past works
  - about a railway OUTSIDE the Klang Valley (Jakarta, Singapore, Penang, \
overseas)
  - a question, a travel plan, a fare query, or a request for directions
  - praise, nostalgia, a photo caption, or general chatter

Judge the author's intent, not whether the words sound negative. "LRT rosak \
lagi" from someone stuck on a platform is live. "LRT rosak sebab politician X" \
is not — it is using a breakdown as a punchline.

Malay, English and mixed Malay-English posts are all normal here. Treat them \
equally.

POST:
{post}"""


def _call_gemini(prompt: str, timeout: float = GATE_TIMEOUT_SECONDS) -> str:
    """Raw gate reply from Gemini. Raises on any failure."""
    import google.generativeai as genai
    from agents.rag_agent import GEMINI_MODEL
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel(GEMINI_MODEL)
    resp = model.generate_content(prompt, request_options={"timeout": timeout})
    return (resp.text or "").strip()


def _call_groq(prompt: str, timeout: float = GATE_TIMEOUT_SECONDS) -> str:
    """Raw gate reply from a Groq-hosted model. Raises on any failure."""
    import httpx
    from agents.rag_agent import GROQ_CHAT_URL, GROQ_VERIFY_MODEL
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY not configured")
    r = httpx.post(
        GROQ_CHAT_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={"model": GROQ_VERIFY_MODEL,
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0,
              "response_format": {"type": "json_object"}},
        timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"Groq HTTP {r.status_code}: {r.text[:160]}")
    return r.json()["choices"][0]["message"]["content"].strip()


def is_live_report(text: str, timeout: float = GATE_TIMEOUT_SECONDS) -> dict:
    """Is this post reporting a live Klang Valley service problem?

    Returns {"live": bool, "why": str, "checked_by": str | None}.

    live is True whenever the answer is yes OR the check could not be made —
    see FAILS OPEN above. checked_by is None when no verdict was obtained, so
    a caller can tell "the gate said keep it" from "the gate never ran".
    """
    if not (text or "").strip():
        return {"live": True, "why": "empty post, nothing to judge",
                "checked_by": None}

    prompt = PROMPT.format(post=text[:1000])
    order = (["groq", "gemini"] if GATE_PROVIDER == "groq"
             else ["gemini", "groq"])
    callers = {"gemini": _call_gemini, "groq": _call_groq}

    for provider in order:
        try:
            raw = callers[provider](prompt, timeout)
            if raw.startswith("```"):                 # strip markdown fences
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed = json.loads(raw.strip())
            live = parsed.get("live")
            if not isinstance(live, bool):
                # Anything other than a boolean is not an answer to the
                # question asked. Try the other provider rather than guessing
                # what "maybe" was supposed to mean.
                raise ValueError(f"unusable verdict {live!r}")
            return {"live": live,
                    "why": str(parsed.get("why") or "")[:80],
                    "checked_by": provider}
        except Exception as e:
            print(f"[Gate] intent check via {provider} failed "
                  f"({type(e).__name__})")

    print("[Gate] no provider available — keeping the alert (fail open)")
    return {"live": True, "why": "gate unavailable", "checked_by": None}


def filter_alert(text: str, *, official: bool = False,
                 timeout: float = GATE_TIMEOUT_SECONDS) -> dict:
    """The decision the ingestion path needs, with the skip rules applied.

    Returns {"alert": bool, "why": str, "checked_by": str | None}, where alert
    is whether this post should keep its disruption_alert flag.
    """
    if not INTENT_GATE:
        return {"alert": True, "why": "gate disabled", "checked_by": None}
    if official:
        return {"alert": True, "why": "official source, not gated",
                "checked_by": None}
    verdict = is_live_report(text, timeout=timeout)
    return {"alert": verdict["live"], "why": verdict["why"],
            "checked_by": verdict["checked_by"]}
