# LRT Companion

**An agentic AI companion for real-time LRT disruption alerts and hyper-personalised rerouting in the Klang Valley.**

Final Year Project · Yio Lim Hoong (TP069098) · BSc (Hons) Computer Science (Artificial Intelligence)
Asia Pacific University of Technology & Innovation · Supervisor: Ts. Dr. Law Foong Li

| | |
|---|---|
| **Live application** | https://lrtcompanionapp.vercel.app |
| **API** | https://lrt-companion-api.onrender.com |
| **API docs (Swagger)** | https://lrt-companion-api.onrender.com/docs |

---

## What it does

Klang Valley rail disruptions are announced 15–30 minutes late and rarely come with an
alternative route. LRT Companion detects disruptions from crowd and social signals,
reroutes commuters around them, and answers procedural questions from official Prasarana
documents.

| Feature | Description |
|---|---|
| **Report Disruption** | Free-text report classified for sentiment and issue type |
| **Line Status** | All 8 rail lines, auto-refreshing, with source-weighted corroboration |
| **Plan Trip** | Disruption-aware routing across 187 stations with 7 personal preferences |
| **Fares & FAQ** | Retrieval-grounded chatbot over 41 official documents |
| **Voice Command** | Hands-free trip planning, English and Bahasa Malaysia |
| **Settings** | Saved stations and preferences applied to every route |

---

## Architecture

A central FastAPI **orchestrator** dispatches each request to exactly one specialist agent.
Agents never call one another, so execution stays traceable.

```
Frontend (Next.js)
      |
  Orchestrator (FastAPI)
      |
  +---+-----------+-------------+------------+
  |               |             |            |
NLP Agent   Rerouting Agent   RAG Agent   Voice Agent
  |               |             |            |
  +---------------+-------------+------------+
                  |
        Supabase (PostgreSQL + pgvector)
```

**Design principle — a deliberate hybrid.** Machine learning is confined to the components
that can be trained and verified (classification, retrieval, transcription). Routing,
corroboration and fare lookup are exact deterministic algorithms, so the decisions a
stranded commuter must trust are never probabilistic.

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js (App Router), React, TypeScript, Leaflet |
| Backend | Python 3.12, FastAPI, Uvicorn |
| Database | Supabase (PostgreSQL + pgvector) |
| Classification | TF-IDF + Logistic Regression + SMOTE (scikit-learn, imbalanced-learn) |
| Routing | NetworkX — Dijkstra with Yen's K-shortest-paths over GTFS data |
| Retrieval | gemini-embedding-2 (3072-dim) + pgvector cosine search |
| Generation | Gemini Flash Lite (grounded answers, low-confidence fallback) |
| Speech-to-text | Whisper large-v3 via Groq API |
| Hosting | Vercel (frontend) · Render (backend) · Supabase (database) |

---

## Running locally

### Prerequisites
- Python 3.12+
- Node.js 18+
- A Supabase project with the `pgvector` extension enabled

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Create `backend/.env` with the following **variable names** (supply your own values):

```
GEMINI_API_KEY=
GOOGLE_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_SERVICE_KEY=
X_BEARER_TOKEN=            # optional — live X ingestion
GROQ_API_KEY=              # optional — hosted Whisper
WHISPER_BACKEND=groq       # groq | local | auto
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Create `frontend/.env.local`:

```
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
```

Open http://localhost:3000

> **Note:** `.env` files are gitignored and must never be committed.

---

## Tests

```bash
cd backend
python -m pytest -q
```

The suite covers routing, corroboration, fare lookup, station detection, the classifier
contract, voice cascade and every API endpoint.

---

## Model performance

Held-out test set of 102 hand-labelled posts, never used in training or model selection.

| Classifier | Accuracy | Macro-F1 |
|---|---|---|
| Sentiment (3-class) | 85.3% | 0.498 |
| Issue type (7-class) | 62.7% | 0.650 |

Four classifiers were compared on identical features. **Logistic Regression** was deployed
over the higher-scoring Linear SVM because the confidence-gated fallback requires native
probability estimates (`predict_proba`), which `LinearSVC` does not provide.

---

## Repository layout

```
backend/          FastAPI app, agents, models, tests
  agents/         nlp · rerouting · rag · transcribe · ingestion · fare_lookup
  api/            route handlers
  models/         shipped .joblib classifiers
  tests/          pytest suite
frontend/         Next.js app (11 routes)
data/             GTFS network, NLP corpus, RAG knowledge base
scripts/          training, evaluation and preprocessing scripts
```

---

## Data statement

The raw scraped social-media corpus is retained locally and is **not redistributed** in this
repository. The published dataset contains only the processed text, post identifiers and the
assigned labels; author names, account identifiers, follower counts, profile metadata and
direct post URLs have been removed in accordance with platform terms and standard research
data-sharing practice. The preprocessing pipeline that produced this dataset is documented in
`scripts/nlp_preprocessing.py` and in Section 3.4 of the project report.

## Further documentation

See `PROJECT_OVERVIEW.md` for the full project description, requirements evidence and
design rationale.
