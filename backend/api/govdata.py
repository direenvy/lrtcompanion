"""
Serve cached gov-data integration status.
Populated by scripts/fetch_govdata.py — re-run that script to refresh.
"""
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/govdata", tags=["GovData"])

CACHE = Path(__file__).resolve().parent.parent.parent / "data" / "govdata" / "cache.json"


@router.get("")
def get_govdata():
    if not CACHE.exists():
        raise HTTPException(
            status_code=404,
            detail="Gov data cache not yet generated. Run scripts/fetch_govdata.py.",
        )
    return json.loads(CACHE.read_text(encoding="utf-8"))
