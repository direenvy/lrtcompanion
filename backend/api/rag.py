from fastapi import APIRouter
from pydantic import BaseModel
from agents.rag_agent import answer
from db.supabase_client import log_chat, log_feedback

router = APIRouter(prefix="/api/rag", tags=["RAG"])


class HistoryItem(BaseModel):
    role: str   # "user" | "assistant"
    text: str


class RAGRequest(BaseModel):
    question: str
    top_k: int = 5
    history: list[HistoryItem] = []


@router.post("/chat")
def chat(request: RAGRequest):
    """
    Answer a user question using the RAG knowledge base (38 official documents).
    Supports multi-turn conversation via optional history.
    Returns a grounded answer with source references.
    """
    history = [h.dict() for h in request.history] if request.history else None
    result = answer(request.question, top_k=request.top_k, history=history)

    # Log to Supabase (non-blocking — ignore errors)
    log_chat(request.question, result.get("answer", ""), result.get("mode", "keyword"))

    return result


class FeedbackRequest(BaseModel):
    question: str
    answer: str
    rating: int   # 1 or -1


@router.post("/feedback")
def feedback(request: FeedbackRequest):
    """Log user thumbs-up / thumbs-down on a chatbot answer."""
    log_feedback(request.question, request.answer, request.rating)
    return {"ok": True}
