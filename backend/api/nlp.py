from fastapi import APIRouter
from pydantic import BaseModel
from agents.nlp_agent import predict
from db.supabase_client import log_disruption

router = APIRouter(prefix="/api/nlp", tags=["NLP"])


class NLPRequest(BaseModel):
    text: str


@router.post("/detect")
def detect(request: NLPRequest):
    """
    Detect sentiment and issue type from a social media post or complaint.
    Returns disruption_alert=True if a disruption is detected, plus real
    confidence scores for each sentiment and issue class.
    """
    result = predict(request.text)

    # Log disruption alerts to Supabase (non-blocking — ignore errors)
    log_disruption(
        text=request.text,
        sentiment=result["sentiment"],
        issue_type=result["issue_type"],
        disruption_alert=result["disruption_alert"],
        method=result.get("method"),
    )

    return result
