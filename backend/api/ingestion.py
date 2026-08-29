from fastapi import APIRouter
from agents.ingestion_agent import run_pull, get_status

router = APIRouter(prefix="/api/ingest", tags=["Ingestion"])


@router.post("/pull")
def pull():
    """On-demand poll of the live X feed (for demos). Never raises —
    returns status 'ok' / 'rate_limited' / 'error' with honest counters."""
    return run_pull()


@router.get("/status")
def status():
    """Live-ingestion counters for the dashboard tile."""
    return get_status()
