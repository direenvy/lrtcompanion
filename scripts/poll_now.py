"""
Run one X ingestion poll, by hand.

This is the whole trigger when INGEST_TRIGGER=manual: no background thread, no
scheduler, nothing calling the endpoint but you. The X quota is capped monthly
and every poll spends part of it, so this keeps that spending deliberate.

The token is read from backend/.env and sent as a header. It is never printed,
never passed on the command line (where it would land in your shell history),
and never needs to exist anywhere you might paste it by accident.

    cd D:/FYP
    python scripts/poll_now.py                 # the deployed backend
    python scripts/poll_now.py --local         # http://127.0.0.1:8000
    python scripts/poll_now.py --url https://...

What it does NOT do: accumulate anything while you are not looking. X's recent
search reaches back 7 days, so a gap longer than that loses those posts
permanently. That is the cost of manual control, and it is the right trade
only if you actually run it.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent

DEPLOYED = "https://lrt-companion-api.onrender.com"
LOCAL = "http://127.0.0.1:8000"


def read_env(name: str) -> str:
    """One value out of backend/.env, without importing the backend."""
    env = ROOT / "backend" / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="backend base URL")
    ap.add_argument("--local", action="store_true",
                    help=f"shorthand for --url {LOCAL}")
    ap.add_argument("--timeout", type=int, default=180,
                    help="seconds (default 180: a sleeping free-tier container "
                         "takes 60-100 s to wake before it can even poll)")
    args = ap.parse_args()

    base = args.url or (LOCAL if args.local else DEPLOYED)
    token = read_env("INGEST_TRIGGER_TOKEN")

    req = urllib.request.Request(f"{base}/api/ingest/pull", data=b"",
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Ingest-Token", token)

    print(f"polling {base} …", end="", flush=True)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:200]
        print(f"\rHTTP {e.code} after {time.time() - t0:.0f}s: {body}")
        if e.code == 401:
            print("\nThe host has INGEST_TRIGGER_TOKEN set to something else, "
                  "or backend/.env has no INGEST_TRIGGER_TOKEN line. The two "
                  "must match exactly.")
        return 1
    except Exception as e:
        print(f"\rfailed after {time.time() - t0:.0f}s: "
              f"{type(e).__name__}: {str(e)[:120]}")
        return 1

    print(f"\r{base} · {time.time() - t0:.0f}s")
    print(json.dumps(out, indent=2))

    status = out.get("status")
    if status == "rate_limited":
        print("\nX returned 429. Nothing was lost — the cursor is unchanged, "
              "so the next poll picks up from the same place.")
    elif status == "error":
        print(f"\nThe poll reported an error rather than crashing: "
              f"{out.get('detail', '')[:160]}")
    elif out.get("scanned") == 0:
        print("\nNo new posts since the last poll. Expected if you ran this "
              "recently — the cursor only returns what arrived after it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
