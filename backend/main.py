import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.nlp import router as nlp_router
from api.rag import router as rag_router
from api.rerouting import router as rerouting_router
from api.orchestrator import router as orchestrator_router
from api.dashboard import router as dashboard_router
from api.govdata  import router as govdata_router
from api.ingestion import router as ingestion_router
from api.voice import router as voice_router
from agents.ingestion_agent import start_polling

app = FastAPI(title="LRT Companion API", version="1.0.0")

# CORS: localhost + private LAN (unchanged for local dev), plus a comma-separated
# list of production origins from the CORS_ALLOWED_ORIGINS env var — that is
# how the Vercel URL gets whitelisted without a code change per environment.
_ALLOWED_ORIGIN_REGEX = (
    r"(https://[a-zA-Z0-9-]+\.vercel\.app|"      # every Vercel deploy / preview
    r"http://(localhost|127\.0\.0\.1|"           # local dev
    r"10\.[0-9]+\.[0-9]+\.[0-9]+|"               # private LAN
    r"172\.(1[6-9]|2[0-9]|3[01])\.[0-9]+\.[0-9]+|"
    r"192\.168\.[0-9]+\.[0-9]+):3000)"
)
_EXTRA_ORIGINS = [o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_EXTRA_ORIGINS,
    allow_origin_regex=_ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(nlp_router)
app.include_router(rag_router)
app.include_router(rerouting_router)
app.include_router(orchestrator_router)
app.include_router(dashboard_router)
app.include_router(govdata_router)
app.include_router(ingestion_router)
app.include_router(voice_router)


@app.on_event("startup")
def _start_live_ingestion():
    # No-op unless X_BEARER_TOKEN is set in backend/.env
    start_polling()


@app.on_event("startup")
def _warm_transcriber():
    """Page the Whisper weights in on a background thread.

    Loading is ~1.5 GB and takes tens of seconds; doing it on the first request
    would make one unlucky user wait that long mid-sentence. Off the main
    thread so the API answers immediately either way — /api/voice/stt-status
    reports false until it is ready, and the frontend falls back to the browser
    recogniser in the meantime.
    """
    import threading
    from agents import transcribe_agent
    threading.Thread(target=transcribe_agent.warm, daemon=True).start()


@app.get("/")
def root():
    return {"status": "LRT Companion API is running"}
