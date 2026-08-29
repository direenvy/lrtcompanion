"""
Exact fare lookup — answers "how much from X to Y" questions directly from the
validated fare matrices instead of relying on retrieval.

Why: the fare tables are exact data. Every station's fare row mentions every
other station, so bag-of-words or embedding retrieval can pick a chunk for the
WRONG origin and ground a wrong number. A deterministic lookup cannot.

Data (see data/raw/fares/, extracted from official Rapid KL sources July 2026):
- integrated_fares_cash.csv / integrated_fares_cashless.csv — 156-station
  integrated network (LRT KJ, LRT AG/SP, Monorail, BRT, MRT KG, MRT PY)
- sal_fares_{cash,cashless,concession}.csv — 20-station LRT3 Shah Alam Line
  (fare-wise separate; combined journeys pay both fares)

Both matrices are symmetric (validated), so origin/destination order is free.
"""

import csv
import re
from pathlib import Path

FARES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "raw" / "fares"

# Words that must appear for a question to count as a fare question
_FARE_WORDS = ("fare", "fares", "price", "cost", "how much", "berapa", "harga", "tambang")

_loaded = False
_integrated: dict[str, dict] = {}   # cash / cashless -> {station: {station: fare}}
_sal: dict[str, dict] = {}          # cash / cashless / concession
_int_names: list[str] = []          # display names, longest first
_sal_names: list[str] = []


def _norm(s: str) -> str:
    """Lowercase, collapse punctuation/whitespace, so 'Dato' Menteri' matches."""
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def _load_matrix(path: Path) -> dict[str, dict[str, float]]:
    with path.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    # integrated CSVs have a 'line' column; SAL CSVs don't
    first_fare_col = 3 if header[2] == "line" else 1
    names = header[first_fare_col:]
    matrix: dict[str, dict[str, float]] = {}
    for r in rows[1:]:
        name = r[1] if first_fare_col == 3 else r[0]
        matrix[name] = {n: float(v) for n, v in zip(names, r[first_fare_col:])}
    return matrix


def _ensure_loaded():
    global _loaded, _int_names, _sal_names
    if _loaded:
        return
    _integrated["cash"] = _load_matrix(FARES_DIR / "integrated_fares_cash.csv")
    _integrated["cashless"] = _load_matrix(FARES_DIR / "integrated_fares_cashless.csv")
    _sal["cash"] = _load_matrix(FARES_DIR / "sal_fares_cash.csv")
    _sal["cashless"] = _load_matrix(FARES_DIR / "sal_fares_cashless.csv")
    _sal["concession"] = _load_matrix(FARES_DIR / "sal_fares_concession.csv")
    _int_names = sorted(_integrated["cash"].keys(), key=len, reverse=True)
    _sal_names = sorted(_sal["cash"].keys(), key=len, reverse=True)
    _loaded = True


def _find_stations(question: str) -> list[tuple[str, str, int]]:
    """Return [(name, table, position)] for stations mentioned in the question,
    longest-name-first so 'Stadium Kajang' wins over 'Kajang'."""
    q = " " + _norm(question) + " "
    found: list[tuple[str, str, int]] = []
    taken: list[tuple[int, int]] = []   # consumed spans

    for table, names in (("integrated", _int_names), ("sal", _sal_names)):
        for name in names:
            n = _norm(name)
            # strip line qualifiers like "(kelana jaya line)" for matching
            n_clean = re.sub(r"\s*\(.*\)$", "", n).strip()
            for candidate in {n, n_clean}:
                if len(candidate) < 4:
                    continue
                i = q.find(" " + candidate + " ")
                if i < 0:
                    continue
                span = (i, i + len(candidate))
                if any(s < span[1] and span[0] < e for s, e in taken):
                    continue          # overlaps an already-matched longer name
                taken.append(span)
                found.append((name, table, i))
                break

    # Fuzzy fallback for names the exact pass missed. Speech-to-text writes
    # local names in whichever orthography it settled on — "Kerinchi" comes
    # back as "Kerinci" from a Malay-detected transcript — and an exact table
    # lookup then finds nothing, so a question the fare data can answer exactly
    # falls through to RAG and is refused.
    #
    # The cutoff here is HIGHER than the routing one (80). A wrong route is
    # visible and recoverable; a confidently quoted wrong fare is neither, and
    # exactness is the whole reason this module exists instead of retrieval.
    if len(found) < 2:
        found.extend(_fuzzy_stations(q, taken, {n for n, _, _ in found}))

    found.sort(key=lambda x: x[2])    # order of appearance in the question
    return found


_FUZZY_CUTOFF = 88


def _fuzzy_stations(q: str, taken: list[tuple[int, int]],
                    already: set[str]) -> list[tuple[str, str, int]]:
    """Near-miss station names in the already-normalised question `q`."""
    try:
        from rapidfuzz import fuzz
    except ImportError:
        return []

    words = [(m.start(), m.group()) for m in re.finditer(r"[a-z0-9]+", q)]
    out: list[tuple[str, str, int]] = []
    used: set[int] = set()

    for table, names in (("integrated", _int_names), ("sal", _sal_names)):
        for size in (3, 2, 1):                    # 'bandar tasik selatan' first
            for i in range(len(words) - size + 1):
                if set(range(i, i + size)) & used:
                    continue
                gram = " ".join(w for _, w in words[i:i + size])
                if len(gram) < 4:
                    continue
                best, best_score = None, 0.0
                for name in names:
                    if name in already:
                        continue
                    n = re.sub(r"\s*\(.*\)$", "", _norm(name)).strip()
                    score = fuzz.ratio(gram, n)
                    if score > best_score:
                        best, best_score = name, score
                if best is None or best_score < _FUZZY_CUTOFF:
                    continue
                pos = words[i][0]
                if any(s < pos + len(gram) and pos < e for s, e in taken):
                    continue
                used |= set(range(i, i + size))
                already.add(best)
                taken.append((pos, pos + len(gram)))
                out.append((best, table, pos))
    return out


def try_answer(question: str) -> str | None:
    """Return an exact-fare answer, or None if this isn't a fare-pair question."""
    ql = question.lower()
    if not any(w in ql for w in _FARE_WORDS):
        return None
    try:
        _ensure_loaded()
    except Exception:
        return None                    # fare CSVs missing — fall back to RAG

    matches = _find_stations(question)
    # need two distinct stations; same-name different-table pairs don't count
    if len(matches) < 2 or matches[0][0] == matches[1][0]:
        return None
    (a, table_a, _), (b, table_b, _) = matches[0], matches[1]

    # Interchange names (Bandar Utama) exist in both tables — if one table
    # covers BOTH stations, the journey is within that table, not cross-network.
    if a in _sal["cash"] and b in _sal["cash"]:
        table_a = table_b = "sal"
    elif a in _integrated["cash"] and b in _integrated["cash"]:
        table_a = table_b = "integrated"

    if table_a == table_b == "integrated":
        cash, cashless = _integrated["cash"][a][b], _integrated["cashless"][a][b]
        return (f"**{a} to {b} costs RM{cash:.2f} cash / RM{cashless:.2f} cashless.** "
                f"Cashless means a Touch 'n Go card or bank card, and is the cheaper way to pay. "
                f"Source: official Rapid KL integrated fare table.")

    if table_a == table_b == "sal":
        cash, cashless = _sal["cash"][a][b], _sal["cashless"][a][b]
        conc = _sal["concession"][a][b]
        return (f"**{a} to {b} on the LRT Shah Alam Line costs RM{cash:.2f} cash / "
                f"RM{cashless:.2f} cashless (RM{conc:.2f} concession).** "
                f"Source: official LRT3 fare table.")

    # Cross-network: LRT3 + integrated network via Bandar Utama, two fares apply
    sal_st, int_st = (a, b) if table_a == "sal" else (b, a)
    hub_sal, hub_int = "Bandar Utama", "Bandar Utama"
    try:
        sal_cash = _sal["cash"][sal_st][hub_sal]
        sal_less = _sal["cashless"][sal_st][hub_sal]
        int_cash = _integrated["cash"][hub_int][int_st]
        int_less = _integrated["cashless"][hub_int][int_st]
    except KeyError:
        return None
    return (f"**{sal_st} to {int_st} costs about RM{sal_cash + int_cash:.2f} cash / "
            f"RM{sal_less + int_less:.2f} cashless in total.** "
            f"The LRT Shah Alam Line has its own fare, so you pay two fares: "
            f"{sal_st} to Bandar Utama (RM{sal_cash:.2f}/{sal_less:.2f}), then transfer "
            f"to the MRT at Bandar Utama for the rest (RM{int_cash:.2f}/{int_less:.2f}). "
            f"Source: official Rapid KL fare tables.")
