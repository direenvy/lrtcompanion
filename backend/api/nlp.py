from fastapi import APIRouter
from pydantic import BaseModel
from agents.intent_gate import filter_alert
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

    # The classifier answers "negative, and about a service issue". The gate
    # asks the prior question — is this a report of a live problem at all?
    #
    # This path needs it more than the scraped one does. Replaying the real
    # log showed the single false confirmation in the data was built from two
    # IN-APP reports: "go to taipan from bukit jalil" (a navigation request)
    # and "got bomb at lrt bukit jalil" (a prank), nine minutes apart. At 1.0
    # each that reached the 2.0 threshold and would have cut Bukit Jalil out
    # of everyone's routing. Deliberate reports carry the highest weight, so
    # a junk one does the most damage.
    #
    # Off by default (INTENT_GATE=1) and fails open, as everywhere else.
    method = result.get("method")
    gate = {"alert": True, "why": "gate disabled", "checked_by": None}
    if result["disruption_alert"]:
        gate = filter_alert(request.text)
        if not gate["alert"]:
            method = f"{method or 'unknown'}+gate_filtered"

    # Log disruption alerts to Supabase (non-blocking — ignore errors)
    log_disruption(
        text=request.text,
        sentiment=result["sentiment"],
        issue_type=result["issue_type"],
        disruption_alert=result["disruption_alert"] and gate["alert"],
        method=method,
    )

    # The caller is told what was logged, not just what was classified — a
    # form that says "reported" while the row carries no alert flag would be
    # lying to the person who filled it in.
    if result["disruption_alert"] and not gate["alert"]:
        result = {**result, "disruption_alert": False,
                  "gate_filtered": True, "gate_reason": gate["why"]}
    return result
