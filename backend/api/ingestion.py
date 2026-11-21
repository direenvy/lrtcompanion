import hmac
import os

from fastapi import APIRouter, Header, HTTPException

from agents.ingestion_agent import INGEST_TRIGGER, get_status, run_pull

router = APIRouter(prefix="/api/ingest", tags=["Ingestion"])

# A shared secret for the scheduled caller.
#
# When polling is driven externally this endpoint is the only thing that makes
# ingestion happen, and each call spends part of a capped monthly X quota. An
# open POST would let anyone drain it, so a token is required whenever one is
# configured. Unset, the endpoint stays open — which keeps the demo button on
# the dashboard working on a local run, and means an existing deployment is
# not broken by this change.
INGEST_TOKEN = os.getenv("INGEST_TRIGGER_TOKEN", "").strip()


def _authorised(supplied: str | None) -> bool:
    if not INGEST_TOKEN:
        return True
    # compare_digest, not ==, so the check does not leak the token's length or
    # prefix through timing.
    return bool(supplied) and hmac.compare_digest(supplied, INGEST_TOKEN)


@router.post("/pull")
def pull(x_ingest_token: str | None = Header(default=None)):
    """On-demand poll of the live X feed. Never raises on a poll failure —
    returns status 'ok' / 'rate_limited' / 'error' with honest counters.

    This is the scheduled entry point when INGEST_TRIGGER=external: the call
    both wakes a sleeping instance and runs the poll.
    """
    if not _authorised(x_ingest_token):
        raise HTTPException(status_code=401, detail="invalid ingest token")
    return run_pull()


@router.get("/status")
def status():
    """Live-ingestion counters for the dashboard tile."""
    out = get_status()
    # Say who is supposed to be driving the polling. Without this, "last_poll
    # was hours ago" is ambiguous between a broken scheduler and a tier whose
    # in-process thread stopped when the container slept.
    out["trigger"] = INGEST_TRIGGER
    out["trigger_token_required"] = bool(INGEST_TOKEN)
    return out
