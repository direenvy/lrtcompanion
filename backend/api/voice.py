"""
Voice assistant endpoint — turns a spoken sentence like
"I'm stuck at Kampung Baru, I want to go to Masjid Jamek" into:
  1. station extraction (in the order spoken: first = where they are,
     last = where they want to go)
  2. NLP classification (a disruption report is logged so the status board
     and every other user's routing benefit from it)
  3. a route from the existing rerouting agent, avoiding any stations
     currently reported disrupted (same live blocks as the Plan Trip page)
  4. a short spoken-friendly reply the frontend reads aloud

Speech-to-text happens in the browser (Web Speech API); this endpoint only
receives the transcript, so it stays fully offline-testable.
"""
import os
import re
import tempfile

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

from rapidfuzz import fuzz

from agents import transcribe_agent
from agents.nlp_agent import predict
from agents.rerouting_agent import reroute
from api.dashboard import (_COMMON_WORD_STATIONS, _CONDITIONAL_STATION_NAMES,
                           _STATION_NAMES, _STATION_STOP_IDS, get_line_status)
from db.supabase_client import log_disruption

router = APIRouter(prefix="/api/voice", tags=["Voice"])

# Official line names for spoken directions
LINE_NAMES_EN = {
    "KJ":  "LRT Kelana Jaya Line",
    "AG":  "LRT Ampang Line",
    "PH":  "LRT Sri Petaling Line",
    "KGL": "MRT Kajang Line",
    "PYL": "MRT Putrajaya Line",
    "MR":  "KL Monorail Line",
    "BRT": "BRT Sunway Line",
    "SA":  "LRT Shah Alam Line",
}
LINE_NAMES_MS = {
    "KJ":  "LRT Laluan Kelana Jaya",
    "AG":  "LRT Laluan Ampang",
    "PH":  "LRT Laluan Sri Petaling",
    "KGL": "MRT Laluan Kajang",
    "PYL": "MRT Laluan Putrajaya",
    "MR":  "Monorel KL",
    "BRT": "BRT Sunway",
    "SA":  "LRT Laluan Shah Alam",
}


class VoiceRequest(BaseModel):
    text: str
    origin_hint: str | None = None   # set when a previous turn asked "where to?"
    lang: str = "en"                 # "en" | "ms" — language of the spoken reply
    # Lower-ranked hypotheses from the recogniser, best-first. Browsers return a
    # RANKED LIST, not one answer, and for Malaysian place names the correct
    # reading is routinely not the top one ("Kerinchi" -> "Corinthian",
    # "Kerinchi", "car inchi"). Reading only [0] throws the right answer away.
    alternatives: list[str] = []
    # Station offered in the previous turn's "did you mean X?" question. A bare
    # "yes" only means something if we remember what was asked.
    pending_station: str | None = None


def _spoken(name: str) -> str:
    """Station name as it should be SPOKEN: title-case, sponsored suffix
    dropped ('KAMPUNG BARU - CBP COOPBANK PERTAMA' -> 'Kampung Baru')."""
    return name.split(" - ")[0].strip().title()


def _instructions_ms(route: dict) -> str:
    """Malay journey directions, rebuilt from the same segment data as the
    English ones — deterministic templates."""
    segs = route.get("segments", [])
    steps: list[str] = []
    for i, seg in enumerate(segs):
        line = LINE_NAMES_MS.get(seg["line"], seg["line"])
        steps.append(
            f"Naik {line} di {_spoken(seg['from'])} dan turun di "
            f"{_spoken(seg['to'])} — {seg['n_stops']} perhentian, "
            f"kira-kira {seg['minutes']} minit."
        )
        if i < len(segs) - 1:
            nxt = segs[i + 1]
            nxt_line = LINE_NAMES_MS.get(nxt["line"], nxt["line"])
            if nxt["from"] == seg["to"]:
                steps.append(f"Di {_spoken(seg['to'])}, tukar ke platform {nxt_line}.")
            else:
                steps.append(f"Di {_spoken(seg['to'])}, keluar dan berjalan ke "
                             f"{_spoken(nxt['from'])} untuk {nxt_line}.")
    if segs:
        steps.append(f"Anda telah tiba di {_spoken(segs[-1]['to'])}.")
    return " ".join(steps)


def _instructions_en(route: dict) -> str:
    """English spoken directions — same shape as the on-screen ones but with
    speech-friendly station names (no sponsor suffixes, no ALL CAPS)."""
    segs = route.get("segments", [])
    steps: list[str] = []
    for i, seg in enumerate(segs):
        line = LINE_NAMES_EN.get(seg["line"], seg["line"])
        n = seg["n_stops"]
        steps.append(
            f"Board the {line} at {_spoken(seg['from'])} and ride "
            f"{n} stop{'s' if n != 1 else ''} to {_spoken(seg['to'])}, "
            f"about {seg['minutes']} minutes."
        )
        if i < len(segs) - 1:
            nxt = segs[i + 1]
            nxt_line = LINE_NAMES_EN.get(nxt["line"], nxt["line"])
            if nxt["from"] == seg["to"]:
                steps.append(f"At {_spoken(seg['to'])}, change to the "
                             f"{nxt_line} platform.")
            else:
                steps.append(f"At {_spoken(seg['to'])}, exit and walk to "
                             f"{_spoken(nxt['from'])}.")
    if segs:
        steps.append(f"You have arrived at {_spoken(segs[-1]['to'])}.")
    return " ".join(steps)


# Words that must never fuzzy-match into a station name
_FILLER_WORDS = {"station", "stesen", "line", "laluan", "train", "tren",
                 "stuck", "tersekat", "going", "pergi", "want", "nak",
                 # Everyday words that score ABOVE the fuzzy cutoff against a
                 # real station and would otherwise hijack the trip:
                 #   "only" -> CONLAY (80)   "tadi" -> TTDI (75)
                 #   "late" -> JELATEK (72)  "saya" -> SRI RAYA (72)
                 "only", "tadi", "late", "saya", "cheap", "petang"}
# Fuzzy cutoff, measured not guessed. Against a 177-word EN/BM speech
# vocabulary this yields exactly one collision ("only"/CONLAY, now filtered
# above). Dropping to 75 to rescue badly-mangled names such as "karen chi"
# (71) would admit "tadi" -> TTDI — and "tadi" ("just now") is common Malay,
# so the trade is a bad one. Names this mangled need better transcription,
# not looser matching.
_FUZZY_CUTOFF = 80

# Confusion dictionary: transcriptions actually OBSERVED in testing, mapped to
# the station meant. Every entry here is a real failure, not a guess.
#
# These exist because the mishearings that matter cluster at 71-77 similarity —
# just under the cutoff — and the gap cannot be closed by loosening it (see
# above). The pattern is a recogniser preferring a REAL WORD over a place name:
# "Jelatek" becomes "gelatik" (a Java sparrow), "Merdeka" becomes "Odegaard".
# Priors that strong are not beaten by a vocabulary prompt, so the specific
# substitution is corrected by name.
#
# Exact whole-word replacement only, so unlike a lower cutoff this cannot
# create new collisions. Add to it from observed failures — do NOT invent
# spellings that have not been seen.
_STT_MISHEARINGS = {
    # Jelatek (KJ) — Whisper prefers "gelatik", the bird
    "gelatik": "jelatek", "celate": "jelatek", "jalate": "jelatek",
    "jelatik": "jelatek", "gelateh": "jelatek",
    # Kerinchi (KJ) — English soundalikes from the browser recogniser
    "karen chi": "kerinchi", "karenchi": "kerinchi", "karinji": "kerinchi",
    "car inchi": "kerinchi", "corinthian": "kerinchi", "kerinji": "kerinchi",
    # Surian (KGL)
    "suryang": "surian", "suriang": "surian", "surian ke": "surian",
    # Merdeka (KGL) — consistently mis-transcribed as a surname
    "odegaard": "merdeka", "odegard": "merdeka",
    # Setiawangsa (KJ) — spacing splits the compound name
    "setia wangsa": "setiawangsa", "setia wangsah": "setiawangsa",
    # Taman Paramount (KJ) — the generic leading word "Taman" is itself
    # unstable ("Tawang"/"Nama"/"Sama"), and once it goes the whole name drops
    # to ~69 similarity. With "taman" intact it already matches at 86, so only
    # the readings that lose it need listing.
    "tawang palamao": "taman paramount", "nama pramau": "taman paramount",
    "sama pramau": "taman paramount", "tawang paramount": "taman paramount",
    # Bandar Utama (KGL/SA interchange) — Whisper reliably drops "Bandar" to
    # "Wan" ("Wan Utama", "Wan Udama"). The remaining word "Utama" is common
    # Malay ("main / principal") and cannot be fuzzy-matched alone without
    # false positives, so the two-word mis-transcriptions are listed whole.
    "wan utama": "bandar utama", "wan udama": "bandar utama",
    "one utama": "bandar utama", "one udama": "bandar utama",
    "van utama": "bandar utama", "bandar utara": "bandar utama",
}
_MISHEARING_RE = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, _STT_MISHEARINGS), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _fix_mishearings(text: str) -> str:
    """Replace known bad transcriptions with the station actually meant."""
    return _MISHEARING_RE.sub(
        lambda m: _STT_MISHEARINGS[m.group(0).lower()], text)


# Below _FUZZY_CUTOFF the match is not safe to ACT on, but it is often still
# the right station: measured over the mishearings collected in testing, the
# intended station was the top candidate 5 times in 8 and in the top three 7
# times in 8. The information is there; what is missing is permission to use
# it. So anything in this band is offered back as a question rather than
# guessed at silently — "did you mean Jelatek?" — which is both safer than a
# silent guess and more useful than a flat failure.
_SUGGEST_FLOOR = 58

_AFFIRMATIVE = {"yes", "yeah", "yep", "yup", "correct", "right", "ok", "okay",
                "sure", "ya", "yer", "betul", "ye", "haah", "aah", "boleh"}


def _is_affirmative(text: str) -> bool:
    words = re.findall(r"[a-z']+", text.lower())
    return bool(words) and words[0] in _AFFIRMATIVE


def _suggest_station(text: str, already: list[str]) -> tuple[str, float] | None:
    """Best near-miss station for the words that did NOT resolve.

    Returns (STATION, score) when something plausible but sub-threshold exists,
    else None. Deliberately scans 1-2 word fragments, mirroring the fuzzy pass,
    so a mangled two-word name ("tawang palamao") is considered whole.
    """
    lower = _fix_mishearings(text.lower())
    for name in already:                       # blank out what already matched
        lower = lower.replace(name.lower(), " ")
    words = [w for w in re.findall(r"[a-z']+", lower)
             if len(w) >= 4 and w not in _FILLER_WORDS]
    if not words:
        return None

    best: tuple[str, float] | None = None
    for n in (2, 1):
        for i in range(len(words) - n + 1):
            gram = " ".join(words[i:i + n])
            for name in _STATION_NAMES:
                if name.upper() in already:
                    continue
                score = fuzz.ratio(gram, name)
                # Only the uncertain band. A confident score belongs to a name
                # the extractor already took; letting it win here would mask
                # the fragment we actually need a suggestion for.
                if not (_SUGGEST_FLOOR <= score < _FUZZY_CUTOFF):
                    continue
                if best is None or score > best[1]:
                    best = (name.upper(), score)
    return best

# Common-word station names (merdeka/universiti/subang/…) need a guard, or
# ordinary speech ("hari merdeka", "kerja dekat sini") would be read as a
# station. The dashboard gates them on a DISRUPTION verb, which is wrong here:
# a voice turn is a journey request, not an incident report. The natural cue in
# speech is a positional preposition — "at Merdeka", "from Subang", "di
# Universiti" — or the name sitting in origin position before "to"/"ke".
_JOURNEY_POSITION = (
    r"(?:\b(?:at|from|to|near|in|towards?|di|ke|dari|dekat|menuju)\s+{name}\b"
    r"|(?:^|[,.]\s*){name}\s+(?:to|ke)\b)"
)


def _in_journey_position(lower: str, name: str) -> re.Match | None:
    """Match a common-word station only where speech marks it as a place."""
    return re.search(_JOURNEY_POSITION.format(name=re.escape(name)), lower)


def _stations_in_spoken_order(text: str) -> list[str]:
    """Station names found in the transcript, in the order they were spoken.

    Three passes: known mishearings are corrected first, then exact (longest
    names claim their span first, so 'ampang park' beats 'ampang'), then FUZZY
    over the remaining words — speech-to-text mangles Malaysian names ('Ampang'
    -> 'ampong', 'Kampung' -> 'kampong'), and demanding exact spelling from a
    voice interface is unusable."""
    lower = _fix_mishearings(text.lower())
    found: list[tuple[int, str]] = []
    for name in _STATION_NAMES:                     # already longest-first
        m = re.search(r"\b" + re.escape(name) + r"\b(?!\s+line\b)", lower)
        if m:
            found.append((m.start(), name))
            lower = lower[:m.start()] + " " * len(name) + lower[m.start() + len(name):]

    # Common-word names, only where a preposition marks them as a place. Kept
    # OUT of the fuzzy pass below on purpose: fuzzy-matching these is unsafe
    # ("kerja" would score against "kerjaya"), so they must be spoken clearly.
    for name in _CONDITIONAL_STATION_NAMES:
        m = _in_journey_position(lower, name)
        if m:
            at = lower.index(name, m.start())
            found.append((at, name))
            lower = lower[:at] + " " * len(name) + lower[at + len(name):]

    # Fuzzy pass on whatever words remain unclaimed
    words = [(m.start(), m.group()) for m in re.finditer(r"[a-z']+", lower)]
    taken_names = {name for _, name in found}
    candidates: list[tuple[int, str, float, set[int]]] = []
    # Words belonging to a fragment identified as a REPEAT of a station already
    # found. They must be blocked from the shorter passes too: dropping the
    # two-word "ampung baru" only to let the leftover "ampung" match AMPANG
    # reintroduces the same class of error one word down.
    repeat_words: set[int] = set()
    for n in (2, 1):                                # two-word names first
        for i in range(len(words) - n + 1):
            gram = " ".join(w for _, w in words[i:i + n])
            if len(gram) < 4 or (n == 1 and gram in _FILLER_WORDS):
                continue
            # Score every station, then keep ONLY this fragment's best match.
            #
            # Offering a fragment's runner-up is how "ampung baru" (a truncated
            # repeat of Kampung Baru, 96) ended up routed to Kampung Batu (87):
            # the exact pass had already claimed KAMPUNG BARU from the second
            # mention, so the runner-up was the highest name still free. Speech
            # repeats constantly — Whisper itself duplicates whole phrases — so
            # a fragment whose best reading is already accounted for is a
            # REPEAT, and must be dropped rather than reassigned elsewhere.
            best_name, best_score = None, 0.0
            for name in _STATION_NAMES:
                if name in _COMMON_WORD_STATIONS:
                    continue
                score = fuzz.ratio(gram, name)
                if score > best_score:
                    best_name, best_score = name, score
            idxs = set(range(i, i + n))
            if best_name is None or best_score < _FUZZY_CUTOFF:
                continue
            if idxs & repeat_words:
                continue                       # already accounted for
            if best_name in taken_names:
                repeat_words |= idxs           # a second mention, not a new stop
                continue
            candidates.append((words[i][0], best_name, best_score, idxs))
    used_words: set[int] = set(repeat_words)   # repeats are already spoken for
    for pos, name, score, idxs in sorted(candidates, key=lambda c: -c[2]):
        if idxs & used_words or name in taken_names:
            continue
        used_words |= idxs
        taken_names.add(name)
        found.append((pos, name))

    return [name.upper() for _, name in sorted(found)]


# Words that say which END of the journey a station is. People do not reliably
# say origin first — "I want to go to KLCC, I stopped at Kerinchi" is just as
# natural as the other order — so position alone gets the direction backwards.
_ORIGIN_MARKERS = (
    r"(?:stuck|stopped|waiting|standing|stranded)?\s*(?:at|from|near|in)|"
    r"berada\s+di|tersekat\s+di|di|dari|kat"
)
_DEST_MARKERS = (
    r"(?:want(?:ed)?\s+to\s+go|going|go|heading|head|travel(?:ling)?)?\s*to|"
    r"nak\s+(?:ke|pergi)|menuju(?:\s+ke)?|pergi\s+ke|ke"
)


def _assign_roles(text: str, stations: list[str]) -> tuple[str, str] | None:
    """(origin, destination) using the preposition in front of each station.

    The old rule was positional — first spoken is where you are, last is where
    you are going. That silently reverses the trip whenever someone leads with
    their destination, which is common phrasing and gave "you are at KLCC" to a
    user who had said "go to KLCC, I stopped at Kerinchi".

    Returns None when the markers do not settle it, so the caller can keep the
    positional reading rather than guess.
    """
    if len(stations) < 2:
        return None
    # Same correction the extractor applied, or a station found via the
    # confusion dictionary has no literal span here and its preposition is
    # never read — silently dropping back to positional order.
    lower = _fix_mishearings(text.lower())
    origins, dests = [], []
    for name in stations:
        i = lower.find(name.lower())
        if i < 0:
            continue                      # fuzzy hit; no literal span to read
        before = lower[max(0, i - 28):i]
        # Destination is checked first: "want to go to X" contains "to X", and
        # also ends with "go to", which must not be read as an origin "at".
        if re.search(rf"(?:{_DEST_MARKERS})\s+$", before):
            dests.append(name)
        elif re.search(rf"(?:{_ORIGIN_MARKERS})\s+$", before):
            origins.append(name)

    if len(origins) == 1 and len(dests) == 1:
        return origins[0], dests[0]
    # One end marked is enough — the other station is the remaining one.
    others = [s for s in stations if s not in origins + dests]
    if len(dests) == 1 and len(others) == 1:
        return others[0], dests[0]
    if len(origins) == 1 and len(others) == 1:
        return origins[0], others[0]
    return None


def _best_transcript(primary: str, alternatives: list[str]) -> tuple[str, list[str]]:
    """Pick whichever recogniser hypothesis actually resolves to stations.

    Speech engines rank by acoustic likelihood, which for Malaysian place names
    is a poor proxy for correctness — the top hypothesis is frequently an
    English word that sounds similar ("Corinthian" for "Kerinchi"). Every
    hypothesis is cheap to test against the station list, so test them all and
    keep the one that resolves best.

    Ranking, in order:
      1. more EXACT hits      — a station whose name appears literally in the
                                transcript. Counting only "how many stations
                                resolved" is not enough: fuzzy matching at
                                cutoff 80 will happily turn "car pong bar" into
                                KEPONG BARU, so a hypothesis that spells
                                KAMPUNG BARU outright must outrank it.
      2. more stations found  — a trip needs an origin AND a destination, so a
                                hypothesis yielding both is likely the intended
                                sentence
      3. earlier in the list  — ties go to the recogniser's own confidence
    Returns (chosen_transcript, stations). Falls back to the primary transcript
    so behaviour is unchanged when no alternative does better.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for t in [primary, *alternatives]:
        key = " ".join((t or "").lower().split())
        if key and key not in seen:
            seen.add(key)
            ordered.append(t)

    def score(text: str) -> tuple[int, int]:
        stations = _stations_in_spoken_order(text)
        lower = _fix_mishearings(text.lower())
        exact = sum(1 for s in stations if s.lower() in lower)
        return exact, min(len(stations), 2)

    best_text = primary
    best_stations = _stations_in_spoken_order(primary)
    best_score = score(primary)
    for text in ordered[1:]:
        s = score(text)
        if s > best_score:
            best_text, best_score = text, s
            best_stations = _stations_in_spoken_order(text)
        if best_score == (2, 2):       # two stations, both spelled out — done
            break
    return best_text, best_stations


def _live_disrupted_stops(exclude_names: set[str]) -> list[str]:
    """Stop IDs of stations in live reports (red window), minus the user's
    own origin/destination. Empty when Supabase is unavailable."""
    try:
        status = get_line_status()
        return [sid for st in status.get("disrupted_stations", [])
                if st["name"] not in exclude_names
                for sid in st["stop_ids"]]
    except Exception:
        return []


@router.post("/assist")
def assist(request: VoiceRequest):
    # Test every hypothesis the recogniser offered, not just its top pick —
    # see _best_transcript. `text` is then the reading that actually resolved,
    # so classification and the logged report use the corrected sentence too.
    text, stations = _best_transcript(request.text.strip(), request.alternatives)

    # "did you mean X?" answered yes — take the station we offered. Checked
    # before extraction because the confirming utterance ("ya", "betul") names
    # no station at all.
    if request.pending_station and _is_affirmative(text):
        if request.pending_station.upper() not in stations:
            stations = [*stations, request.pending_station.upper()]

    if request.origin_hint and len(stations) <= 1:
        # follow-up turn: previous question was "where do you want to go?"
        stations = [request.origin_hint.upper()] + stations

    # Classify + log: a spoken "stuck at X" is a crowd report like any other,
    # so the status board (and everyone else's routing) learns from it too
    # Local classifier only: the Gemini refinement costs ~9 s and this is an
    # interactive turn. It affects how the report is logged, not the route.
    nlp = predict(text, allow_remote=False)
    log_disruption(
        text=text,
        sentiment=nlp["sentiment"],
        issue_type=nlp["issue_type"],
        disruption_alert=nlp["disruption_alert"],
        method=nlp.get("method"),   # always 'local' here (allow_remote=False)
    )

    ms = request.lang == "ms"

    if not stations:
        # No station named and not a disruption report → treat it as a service
        # QUESTION and answer through the RAG chatbot (fares, My50, refunds,
        # bridging buses…) — the voice assistant and Ask share one brain.
        if not nlp["disruption_alert"] and len(text.split()) >= 3:
            try:
                from agents import rag_agent
                rag = rag_agent.answer(text)
                spoken = re.sub(r"\*+", "", rag.get("answer", "")).strip()
                if spoken:
                    return {"reply": spoken, "mode": "chat", "nlp": nlp}
            except Exception:
                pass   # RAG unavailable — fall through to the station prompt
        # Before giving up: a near-miss is usually the right station (measured
        # top-1 in 5 of 8 observed mishearings). Offer it rather than guess.
        guess = _suggest_station(text, stations)
        if guess:
            return {
                "reply": (f"Adakah anda maksudkan {guess[0].title()}?" if ms else
                          f"Did you mean {guess[0].title()}?"),
                "pending_station": guess[0],
                "need_station": True,
                "nlp": nlp,
            }
        return {
            "reply": ("Sila beritahu saya anda berada di stesen mana — "
                      "contohnya: saya tersekat di Kampung Baru." if ms else
                      "Please tell me which station you are at — for example, "
                      "say: I am stuck at Kampung Baru."),
            "need_station": True,
            "nlp": nlp,
        }

    if len(stations) == 1:
        # The other end was probably spoken but mis-transcribed. Repeating
        # "which station?" traps the user in a loop they cannot escape by
        # saying the name again — it will be misheard the same way. Offer the
        # near-miss instead.
        guess = _suggest_station(text, stations)
        if guess:
            return {
                "reply": (f"Baik, anda di {stations[0].title()}. "
                          f"Adakah anda maksudkan {guess[0].title()}?" if ms else
                          f"Okay, you are at {stations[0].title()}. "
                          f"Did you mean {guess[0].title()}?"),
                "origin": stations[0],
                "pending_station": guess[0],
                "need_destination": True,
                "nlp": nlp,
            }
        return {
            "reply": (f"Baik, anda berada di {stations[0].title()}. "
                      "Anda mahu pergi ke stesen mana?" if ms else
                      f"Okay, you are at {stations[0].title()}. "
                      "Which station do you want to go to?"),
            "origin": stations[0],
            "need_destination": True,
            "nlp": nlp,
        }

    # Prefer the direction the words actually state; fall back to spoken order
    # (first = where you are) only when no preposition settles it.
    roles = _assign_roles(text, stations)
    origin, destination = roles if roles else (stations[0], stations[-1])
    blocked = _live_disrupted_stops(exclude_names={origin, destination})
    route = reroute(origin, destination, disrupted_stops=blocked or None)

    ack = ""
    if nlp["disruption_alert"]:
        ack = (f"Saya telah melaporkan masalah di {origin.title()}. " if ms else
               f"I have reported the problem at {origin.title()}. ")

    if route.get("error"):
        alt = route.get("alternatives") or {}
        walk = (alt.get("walkable_nearby") or [{}])[0]
        if ms:
            walk_txt = (f" Stesen lain yang terdekat ialah {walk['name'].title()}, "
                        f"kira-kira {walk['walk_minutes']} minit berjalan kaki."
                        if walk.get("name") else "")
            body = (f"Maaf, tiada laluan tren dari {origin.title()} ke "
                    f"{destination.title()} buat masa ini. Bas bantuan atau "
                    f"e-hailing seperti Grab adalah pilihan terbaik.{walk_txt}")
        else:
            walk_txt = (f" The nearest other station is {walk['name'].title()}, "
                        f"about {walk['walk_minutes']} minutes on foot."
                        if walk.get("name") else "")
            body = (f"I could not find a train route from {origin.title()} "
                    f"to {destination.title()} right now. A bridging bus or "
                    f"e-hailing like Grab is the best option.{walk_txt}")
        return {
            "reply": ack + body,
            "origin": origin, "destination": destination,
            "route": route, "nlp": nlp,
        }

    mins = route.get("estimated_minutes")
    if ms:
        body = (f"Ini laluan ke {destination.title()}, kira-kira {mins} minit. "
                + _instructions_ms(route))
    else:
        body = (f"Here is the way to {destination.title()}, about {mins} minutes. "
                + _instructions_en(route))
    return {
        "reply": ack + body,
        "origin": origin, "destination": destination,
        "route": route, "nlp": nlp,
    }


class ResolveRequest(BaseModel):
    text: str
    alternatives: list[str] = []


@router.post("/resolve-stations")
def resolve_stations(request: ResolveRequest):
    """Extract origin and destination from a spoken sentence, WITHOUT routing.

    Exists so the Plan Trip page can fill its two station fields by voice while
    keeping its own preference controls and route rendering. Reuses the whole
    voice resolution stack — N-best hypothesis selection, the confusion
    dictionary, and preposition-based direction assignment — so "I want to go
    to KLCC, I stopped at Kerinchi" fills the fields the right way round rather
    than in the order the words happened to arrive.
    """
    text, stations = _best_transcript(request.text.strip(), request.alternatives)

    origin = destination = None
    if len(stations) >= 2:
        roles = _assign_roles(text, stations)
        origin, destination = roles if roles else (stations[0], stations[-1])
    elif len(stations) == 1:
        # One end only — hand it back as the origin and let the user type the
        # other. Guessing which end they meant would be worse than asking.
        origin = stations[0]

    # Below the match threshold a near-miss is usually still the right station
    # (measured top-1 in 5 of 8 observed mishearings), so offer it rather than
    # silently dropping the utterance.
    suggestion = _suggest_station(text, stations) if len(stations) < 2 else None

    return {
        "text": text,
        "origin": origin,
        "destination": destination,
        "stations": stations,
        "suggestion": suggestion[0] if suggestion else None,
    }


@router.get("/stt-status")
def stt_status():
    """Whether Whisper transcription is usable (Groq OR local).

    The frontend asks before recording so it can choose its capture strategy:
    with a Whisper backend up it records audio and posts it here; without, it
    falls back to the browser recogniser. Failing over AFTER the user has
    spoken would lose the utterance, so the choice has to be made in advance.
    """
    order = transcribe_agent._backend_order()
    return {
        "available": transcribe_agent.available(),
        "backend":   order[0] if order else None,   # which backend runs FIRST
        "backends":  order,                          # full priority list
        "model":     transcribe_agent.MODEL_SIZE,
        "device":    transcribe_agent.DEVICE,
        "error":     transcribe_agent.load_error(),
    }


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), lang: str = "en"):
    """Transcribe recorded speech with the local Whisper model.

    Returns {"text", "language", "available"}. `available: false` means the
    model could not be loaded — the caller should fall back to the browser
    recogniser rather than treat it as a failed recording.
    """
    if not transcribe_agent.available():
        return {"text": "", "language": None, "available": False,
                "error": transcribe_agent.load_error()}

    # faster-whisper reads from a path, so the upload is spooled to a temp file
    # and removed afterwards — voice recordings are not ours to keep.
    suffix = os.path.splitext(audio.filename or "")[1] or ".webm"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(await audio.read())
        tmp.close()
        # `lang` is only a fallback for when auto-detect wanders outside the
        # plausible set — it does NOT force the language, which measured worse.
        return transcribe_agent.transcribe(tmp.name, ui_language=lang)
    except Exception as e:
        print(f"[Transcribe] failed: {e}")
        return {"text": "", "language": None, "available": False, "error": str(e)}
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
