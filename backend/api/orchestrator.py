from fastapi import APIRouter
from pydantic import BaseModel
from agents.orchestrator import handle_full_disruption

router = APIRouter(prefix="/api/orchestrator", tags=["Orchestrator"])


class DisruptionRequest(BaseModel):
    text:            str
    origin:          str = ""
    destination:     str = ""   
    disrupted_stops: list[str] = []

@router.post("/disruption")
def disruption_pipeline(request: DisruptionRequest):
    """
    Full 3-agent disruption pipeline:
    1. NLP Agent   — sentiment + issue type + alert flag
    2. Rerouting   — optimal alternative route avoiding disrupted stops
    3. RAG Chatbot — official Rapid KL advice for the situation
    """
    return handle_full_disruption(
        text=request.text,
        origin=request.origin,
        destination=request.destination,
        disrupted_stops=request.disrupted_stops,
    )
