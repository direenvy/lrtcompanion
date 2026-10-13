"""
Choose the fuzzy station-matching threshold from labelled cases.

The station detector is exact substring matching over the 187 GTFS names. It
works, and it is why "masjid jamek stuck" lights up the board — but a commuter
who types "masjid jamik", or a voice transcript that returns "kampong baru",
produces NOTHING: no chip, no line fan-out, no reroute avoidance. The report
is logged and silently ignored.

Fuzzy matching closes that, and is dangerous in exactly one direction. A loose
threshold attributes reports to stations nobody mentioned, and a false
attribution here is not cosmetic: it reddens a line and reroutes people away
from a station that is running. The "shah alam" -> STADIUM SHAH ALAM incident
is the shape of that failure.

So the threshold is chosen against two labelled sets, both required:

  MISSPELLINGS  real typos and transcription errors that MUST resolve
  NEGATIVES     text that must resolve to NOTHING — other Malaysian places,
                partial station names, and the substrings that caused the
                known bug

A threshold is only usable if it satisfies both. If no threshold does, that is
the finding, and fuzzy matching should not be enabled.

    cd D:/FYP
    python scripts/tune_station_fuzzy.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import api.dashboard as dash                          # noqa: E402

THRESHOLDS = [78, 80, 82, 84, 85, 86, 88, 90, 92, 95]


# (text, expected station name). The expected name is the GTFS variant the
# detector stores, which for sponsored names is the base ("kampung baru").
MISSPELLINGS = [
    ("stuck at masjid jamik, no train",            "masjid jamek"),
    ("kampong baru lrt rosak",                     "kampung baru"),
    ("train not moving at danq wangi",              "dang wangi"),
    ("huge crowd at pasar senni right now",        "pasar seni"),
    ("klcc stesen ok but ampamg park jammed",      "ampang park"),
    ("wangsa maju station down",                   "wangsa maju"),       # exact
    ("terkandas kat taman melatti",                 "taman melati"),
    # NOTE the expected spelling: the GTFS name is "bandar tasiK selatan".
    # The first draft of this case expected the typo back and reported a
    # failure the rule had not made — worth keeping as a reminder that the
    # fixture is as likely to be wrong as the code.
    ("bandar tasek selatann platform closed",      "bandar tasik selatan"),
    ("lift broken at setiawangssa",                 "setiawangsa"),
    ("kelana jaya stesen packed",                  "kelana jaya"),       # exact
    ("asia jaia station not working",               "asia jaya"),
    ("train held at hang tua",                     "hang tuah"),
]

# Text that must produce NO station. Each is a real failure mode, not padding.
NEGATIVES = [
    # the known bug: a 2-word place inside a 3-word station name
    "shah alam traffic is terrible today",
    # Malaysian places that are not Klang Valley rail stations
    "flight delayed at klia2 again",
    "jam kat karak highway",
    "penang bridge closed this morning",
    "johor bahru checkpoint packed",
    # partial / generic fragments
    "taman is flooded",
    "bandar baru area has no power",
    "stesen minyak closed",
    # a different network entirely
    "jakarta mrt delayed this morning",
    # ordinary words that are near station names
    "my university class is cancelled",
    "the station wagon broke down",
]


def best_match(text: str, threshold: int):
    """Mirror of the detector's fuzzy pass, so tuning scores the real rule."""
    return dash._fuzzy_detect_stations(text, threshold=threshold)


def main():
    if not hasattr(dash, "_fuzzy_detect_stations"):
        print("api.dashboard has no _fuzzy_detect_stations — nothing to tune.")
        return

    print(f"{len(dash._STATION_NAMES)} station names in the gazetteer")
    print()
    print(f"{'thresh':<9}{'typos resolved':<18}{'negatives clean':<18}note")
    print("-" * 70)

    usable = []
    detail = {}
    for t in THRESHOLDS:
        hits, wrong = [], []
        for text, want in MISSPELLINGS:
            got = [n for n, _ids in best_match(text, t)]
            if want in got:
                hits.append((text, want))
            else:
                wrong.append((text, want, got))
        clean, dirty = [], []
        for text in NEGATIVES:
            got = [n for n, _ids in best_match(text, t)]
            (clean if not got else dirty).append((text, got))

        ok = len(hits) == len(MISSPELLINGS) and len(clean) == len(NEGATIVES)
        if ok:
            usable.append(t)
        detail[t] = (wrong, dirty)
        print(f"{t:<9}{f'{len(hits)}/{len(MISSPELLINGS)}':<18}"
              f"{f'{len(clean)}/{len(NEGATIVES)}':<18}"
              f"{'both correct' if ok else ''}")

    print()
    if usable:
        pick = max(usable)
        print(f"Thresholds satisfying both sets: {usable}")
        print(f"Take the HIGHEST ({pick}). The two errors are not symmetric: a")
        print("missed typo leaves the board exactly as it is today, while a")
        print("false attribution reddens a line and reroutes people away from a")
        print("station that is running. Prefer under-matching.")
    else:
        print("NO threshold satisfies both sets. Fuzzy matching as written")
        print("cannot be enabled safely. The failures at each threshold are")
        print("below — read them before changing the rule rather than the")
        print("number.")

    print()
    print("FAILURES BY THRESHOLD")
    for t in THRESHOLDS:
        wrong, dirty = detail[t]
        if not (wrong or dirty):
            continue
        print(f"  {t}:")
        for text, want, got in wrong:
            print(f"    missed  {want:<22} got {got or 'nothing'}  <- {text[:45]}")
        for text, got in dirty:
            print(f"    FALSE   {str(got):<22}            <- {text[:45]}")


if __name__ == "__main__":
    main()
