# LRT Companion — Project Overview

Canonical positioning, current state, honest blindspots, and examiner Q&A.
Last refreshed: 16 August 2026 — post local-Whisper voice (replacing browser
Web Speech), safe-walk CPTED survey, screen-reader support, deterministic fare
and network bypasses, mobile layout fixes, and Vercel/Render deployment.
**190 offline tests green.**

---

## System Objective (canonical — use this wording everywhere)

> **LRT Companion is an agentic AI decision-support system that fuses crowd-sourced
> disruption reports, official GTFS schedule data, and retrieval-grounded AI to guide
> Klang Valley rail commuters around service disruptions in real time — with
> personalised, plain-language journey guidance.**

### Sub-objectives (all achieved)

1. **Detect** — classify commuter reports into sentiment + issue type with a hybrid
   local-model/LLM pipeline (85.3% sentiment accuracy, 0.650 issue-type macro-F1,
   confidence-gated Gemini fallback at 60%/40% thresholds)
2. **Reroute** — compute top-3 alternatives on the official 187-station / 8-line GTFS
   network with schedule-derived travel times, honouring user preferences and
   explaining the trade-off when preferences cannot be met
3. **Advise** — answer service questions grounded in 41 official Rapid KL documents,
   formatted for low-literacy and elderly readers (≤3 sentences, bolded key fact,
   Malay replies to Malay questions)
4. **Monitor** — aggregate live signals into a per-line status board that feeds back
   into routing ("plan around this")

## Uniqueness (defensible claims)

> *"The first system for the Klang Valley to close the loop between crowd-sourced
> disruption detection and preference-aware rerouting on the official rail network —
> disruptions detected by the community immediately reshape the routes recommended
> to it."*

| vs | What they lack that this system has |
|---|---|
| Google Maps / Moovit | No Malaysian disruption awareness — they route onto a broken line. No crowd-sourced KL signal. No preference relaxation ("your avoid-line costs 18 min — here's the trade-off"). |
| MyRapid PULSE (official) | Announcements only — no rerouting around the announced disruption, no NLP over free-text, no place-based search, no multi-modal fallback (bridging bus / walk / Grab). |
| Academic transit systems | Full closed loop (report → classify → status → reroute → advise) plus a documented iterative-IR cycle (label → SMOTE → LLM augmentation → retrain) with an ablation study. |

**Live-data positioning:** external feeds (X API, Reddit, official 2026 service alerts)
are *pluggable sensors* into the same pipeline — the architecture is live by design;
a paid X feed demonstrates it but does not define it. If a feed dies, every uniqueness
claim above still holds.

---

## What is built (verified working)

### Agents
- **NLP** — TF-IDF + Logistic Regression (SMOTE + Gemini-paraphrase augmented);
  Gemini flash-lite fallback only below confidence thresholds; past-reference
  guard: explicit past-time phrases (EN+BM: "last week", "minggu lepas",
  "semalam"…) and explicit calendar dates more than 2 days old ("On July 5"
  in a news recap; "5hb Julai") suppress the alert flag unless an ongoing marker ("still",
  "since", "masih", "lagi") overrides — a memory of a breakdown is a
  complaint, not a live alert
- **Rerouting** — NetworkX over official GTFS (187 stations, 8 lines incl. LRT3
  Shah Alam); schedule-derived edge times; top-3 alternatives (dedup by line
  sequence, +20-min sanity filter); fuzzy station match (rapidfuzz, did-you-mean);
  free-text **place search** (Nominatim + Photon geocoding, Klang-Valley-bounded,
  nearest-station resolution); named interchanges incl. out-of-station walks
  (Bandar Utama 12 min) and link bridges (Glenmarie 8 min, USJ7 5 min);
  preference relaxation with explicit trade-off messaging; plain-language
  numbered instructions per route
- **RAG** — Gemini embeddings over 1,903 chunks / 41 documents (incl. LRT3 line
  info, LRT3 fare table, and the full 156-station integrated fare matrix
  extracted from the official fare-calculator dataset and cross-validated
  against the published fare images); **canonical vector store is Supabase
  pgvector** (`rag_chunks` table + `match_rag_chunks` cosine-similarity RPC,
  service-role-only access) with the local embedding cache as a documented
  performance layer; retrieval order: fare-lookup → local cache → pgvector →
  keyword fallback; elder-friendly answer format rules; quota-aware resumable
  embedding build (checkpoints across free-tier days)
- **Fare lookup** — station-pair fare questions bypass retrieval entirely and
  answer from the validated matrices (`agents/fare_lookup.py`): deterministic,
  offline, handles LRT3-to-network journeys as two fares via Bandar Utama —
  a wrong-origin chunk can never ground a wrong number
- **Ingestion** — `agents/ingestion_agent.py` polls X search/recent every 30
  min (+ `POST /api/ingest/pull` for demos), classifies through the NLP
  pipeline, dedupes by tweet ID across restarts, and tags each row by trust:
  posts from the official **@AskRapidKL** account (detected via the X
  `author_id`/`username` expansion) are tagged `source: "x_official"` and
  confirm alone; everyone else is `source: "x_live"` (weight 0.4). Every
  scanned tweet — alert or not — is also captured with its prediction into
  `data/nlp/interim/live_x_labelling.csv` as raw material for the live
  labelling pass. Retries transient 5xx with backoff; 429 backs off honestly
- **Voice assistant** — `api/voice.py` + `agents/transcribe_agent.py` +
  `/voice` page: a spoken sentence ("I'm stuck at Kampung Baru, I want to go
  to Masjid Jamek") is transcribed, parsed for stations, classified and logged
  as a crowd report, routed around live blocks, and answered aloud in English
  or Malay; non-routing questions go to the RAG agent, so voice and Fares &
  FAQ share one brain. **Speech-to-text is local Whisper `large-v3`**
  (faster-whisper, int8_float16, ~1.3 s/utterance on an RTX 4050) with Groq's
  hosted Whisper as the deployed backend and the browser recogniser as a final
  fallback — selected by `WHISPER_BACKEND`. Measured resolution on Malaysian
  station names: browser Web Speech ~3/10 → Whisper 6/10 → Whisper with a
  station-name `initial_prompt` 8/10 → 9/10 with the full pipeline (N-best
  hypothesis selection, confusion dictionary, preposition-based direction
  assignment). Voice input is also available as a MODALITY on Report
  Disruption, Plan Trip and Fares & FAQ via `components/VoiceInput.tsx`
- **Orchestrator** — NLP → Reroute → RAG one-shot pipeline (Smart Plan)

### Data & integrations
- Official GTFS from data.gov.my (refreshed July 2026, includes LRT3)
- data.gov.my dashboard card: 187 official stations = 187 local ✓, ridership
  baseline, vehicles honestly "n/a" (rail RT feed broken upstream)
- Supabase: Google OAuth + passwordless 6-digit email OTP; RLS-enabled log
  tables written via service-role key; user preferences synced per account

### Frontend (Sonos-inspired achromatic design system — see DESIGN.md)
- Full-bleed video hero, scroll-scrubbed exploded 5-agent stack, scroll-reveal
  sections, dark stats panel, split feature, closing video card, black footer
  with integrity disclaimer, back-to-top
- Plan Trip: route tabs (Best/Alt), numbered "How to get there" steps, dashed
  walking connectors on the light map, preference/place/typo notices,
  loading skeleton, friendly errors with Retry
- Mobile: hamburger nav, one-column collapse, ≥40px tap targets
- 1-click commute card for signed-in users (home page)
- Line Status: two-tier pills (🔴 disrupted / 🟡 unconfirmed / 🟢 normal) that
  **show the corroboration arithmetic** ("corroboration 0.4 / 2 needed") and
  a 📍 **"Reported at: <station>" drill-down chip** on any affected line, so a
  red card tells you *which* station caused it; monochrome source badges —
  blue "✓ Official RapidKL" for operator posts, "X live" / "user report" for
  the rest (also on the Dashboard feed). New **/incidents** page lists full
  24 h/7 d/30 d history with per-line and per-source filters.
- `/voice` page: press-to-talk, EN/BM, spoken reply, typed fallback
- App pages share one 960px content column (design-system width); Plan Trip's
  map is 460px tall; chat bubbles cap at 620px so long answers stay readable

### Engineering
- **190 pytest tests, green in ~15 s, fully offline** (Gemini/Supabase/geocoding/
  X API blocked by fixtures); suite caught 2 real defects on first run
  (fewest-stops weighting, mode-corrupted minute display). Coverage per module:
  rerouting 24 · line detection 25 · voice 14 · ingestion 11 · line-status tiers
  10 · NLP 10 · fare lookup 8 · API 6.
- **Line attribution → station fan-out:** each alert is annotated with
  `implicated_lines` — the set of lines the report actually affects. An
  explicit line name ("Kelana Jaya line down") stays scoped to that line;
  a bare station name ("Masjid Jamek stuck") fans out to **every line whose
  platform is at that station** (KJ+AG+PH here), because a broken interchange
  breaks all its lines at once. Lines that don't stop there are never touched
  (KGL/PYL/MR/BRT/SA stay green for a Masjid Jamek report). Each affected
  line card carries a 📍 **"Reported at: <station>" drill-down chip**, so a
  red line always says *which* station caused it. Station-level attribution
  still uses 160+ GTFS station names (longest-match, interchange-aware) with
  line-name keywords as fallback — "stuck at Wangsa Maju" attributes to KJ
  without naming it, and doesn't leak into AG/PH.
- **Source-weighted trust model — full reference in `TRUST_MODEL.md`.**
  Signals accumulate weight over *distinct* texts (spam counts once); a line
  or station is only CONFIRMED at weight ≥ **2.0**:
  official @AskRapidKL **2.0** (confirms alone) · in-app report **1.0** ·
  voice report **1.0** · scraped tweet **0.4** (~5 needed) · unknown source
  **0.4** (fails safe). The board shows the arithmetic ("corroboration 0.4 / 2").
- **Two-tier status — fast where being wrong is cheap, careful where it is
  expensive:** any signal instantly shows 🟡 UNCONFIRMED (amber pill; station
  appears as an advisory on Plan Trip with a manual "Avoid anyway" — nobody is
  rerouted). Only weight ≥ 2.0 flips 🔴 DISRUPTED and **acts**: the station's
  stop_ids are injected into every route request and Dijkstra routes around it
  (e.g. KLCC→Masjid Jamek detours via Ampang Park–Titiwangsa when KJ11/KJ12
  are blocked). This kills the single-political-tweet false alarm (0.4 < 2.0)
  and the griefing vector, while keeping early warning faster than any
  official channel. Sponsored GTFS names normalised ("KAMPUNG BARU - CBP
  COOPBANK PERTAMA" matches "kampung baru"); "<station> line" phrasing is a
  line mention, not a station block; if the disrupted station IS the
  origin/destination it is not blocked — the user gets a delay warning instead
- **Personalisation preferences (8, all persisted per account):** priority
  (fastest / fewest stops / fewest transfers) · avoid lines · prefer_shelter
  (weather) · require_wheelchair (hard filter, excludes non-step-free stations
  with `_accessible_sibling` interchange fallback) · require_tactile (warning,
  never severs the network) · max_walk_minutes (bucketed selector, walking
  cap) · prefer_quiet (segment-busyness heuristic from real O-D ridership
  parquet). Every preference has an "already satisfied / trade-off" explanation.
- **Interchange-shelter routing (CSV-driven):** `prefer_shelter` now covers
  transfer walks too. `data/raw/shelter/interchange_shelter.csv` (surveyed
  3 Aug 2026, 18 rows) is the source of truth for which transfer walks are
  weather-covered; only exposed transfers are penalised, and a 🌧 warning fires
  when the best route still uses one (e.g. Bukit Bintang KGL↔MR). Uses a
  normalised name matcher (`_norm_station`) so USJ7/USJ-7/USJ 7 all match.
- **Accessibility data:** `data/raw/accessibility/oku_stations.csv` (187 rows;
  `wheelchair_accessible`, `blind_tactile`, source, verified_date). Where the
  official MyRapid PULSE app and Google Maps disagreed, PULSE was chosen for
  consistency (documented as a data-completeness limitation).
- **Live-data feedback loop:** `data/nlp/interim/live_x_labelling.csv` captures
  every ingested tweet with prediction + method + confidence and empty
  human-label columns; `merge_and_retrain.py --batch` consumes it directly.
- **Supabase transient retry:** a momentary DNS/network blip no longer blanks
  the board — one 0.6-s retry before falling back to the honest degraded
  snapshot; only a sustained outage degrades. Live-tested against a real
  `getaddrinfo failed` incident.
- TypeScript clean (`npx tsc --noEmit` exit 0)

### NLP ablation (report table)

| Stage | Sentiment Acc | Issue Acc | macro-F1 | crowding F1 | staff F1 |
|---|---|---|---|---|---|
| Baseline | 84.3% | 63.7% | 0.502 | 0% | 0% |
| + SMOTE | 86.3% | 67.6% | 0.534 | 0% | 0% |
| + Gemini paraphrase + SMOTE | 85.3% | 67.6% | 0.643 | **75%** | **75%** |
| + merge 1-sample `safety` class | 85.3% | 62.7% | **0.650** | **75%** | **75%** |

(Deployed = last row. Also report-worthy: a 32-config hyperparameter search
selected by 5-fold CV on the augmented training set scored 0.757 in CV but
only 0.565 on the held-out test — Gemini paraphrases of the same source tweet
land in different CV folds, inflating CV scores. `scripts/tune_issue_model.py`
documents the honest protocol; the simpler pre-registered config was kept.)

---

## Traceability matrix (problem statement → system → evidence)

Every sub-problem in report §1.2 must chain to a built capability and
demonstrable evidence. Paste this table (prose-adapted) into the report's
evaluation/conclusion chapter and keep it true.

| Sub-problem (§1.2) | Objective | Built capability | Evidence to show |
|---|---|---|---|
| 1.2.1 Delayed disruption awareness | Detect | NLP classifier (85.3% / 0.650 macro-F1) + live X ingestion (30-min polls, `source: "x_live"`) + in-app crowd reports → Line Status board (30-min red / 4-h amber windows) | Ablation table; live pull counters on dashboard; alert appearing on board during demo |
| 1.2.2 No dynamic rerouting guidance | Reroute | Disruption-aware Dijkstra on official GTFS (187 stations): "plan around this" from a red line, top-3 alternatives, bridging-bus corridors, walkable nearby stations, e-hailing fallback | Live demo: disrupt KJ → reroute avoids it; `test_disrupted_stop_not_in_path`; alternatives panel |
| 1.2.3 Inaccessible SOP/safety info | Advise | RAG over 41 official Prasarana docs (SOPs, law, FAQs) on Supabase **pgvector**; deterministic fare lookup; hallucination-constrained answers with source citations | Chat demo: bridging-bus/refund/SOP question with cited source badges; pgvector row count (1,903) |
| 1.2.4 Fragmented information | Monitor + unified UX | One interface consolidating NLP signals, GTFS routing, and RAG answers; single status board fed by all sources with source badges | The app itself; uniqueness claim; cross-page flows (status → reroute) |
| 1.2.5 No preference-aware rerouting | Personalised routing | Discrete objectives (fastest / fewest stops / fewest transfers), sheltered routing, line avoidance, per-account persistence, **preference relaxation with explicit trade-off disclosure** | Demo: shelter toggle feedback; avoid-KJ relaxation offer; `test_avoid_line_excluded_in_all_routes` |

**Known wording alignment (fixed in report):** §1.2.5 originally promised
continuous "user-weighted" time/cost/exertion weights. Implementation uses
discrete preference modes + relaxation disclosure; the report sentence was
rewritten to match (see the corrected paragraph provided for §1.2.5). Fare
data exists as a lookup, not a routing weight — do not claim cost-weighted
routing.

**UAT cross-coverage:** UAT_KIT tasks validate the matrix with real users —
tasks 4–5 → 1.2.1/1.2.2, task 7 → 1.2.3, task 3 → 1.2.5, task 8 →
personalisation persistence. Quote task success rates per sub-problem in the
evaluation chapter.

---

## Report-ready statements

### Objective 2 descope — "fleet calculation" (paste into the report where the objective is discussed)

> The original objective wording included fleet-level calculation. This was
> consciously descoped: vehicle-level fleet data for Klang Valley rail is not
> publicly available (the official GTFS-Realtime vehicle feed for rail returns
> no data, verified July 2026), and for passenger-facing route decisions the
> service supply is fully captured by the published headways (3–7 minutes per
> line, per day type), which the system already ingests from the official
> GTFS `frequencies.txt`. The objective's intent — routing that reflects
> actual service levels — is therefore met through schedule-derived travel
> times and headway-aware frequency data rather than fleet simulation.

### Corrected §1.2.5 closing sentence (replaces the "user-weighted weightings" claim)

> The results presented directly motivate the preference-weighted routing
> engine of the proposed system, in which commuters select routing objectives
> (fastest, fewest stops, fewest transfers) and accessibility-relevant
> constraints (sheltered routing, avoidance of specific lines), and the system
> explicitly discloses the time cost of each preference — recommending the
> unconstrained alternative when a preference makes a journey substantially
> slower or infeasible, so the trade-off described by Wu et al. is surfaced to
> the commuter rather than silently decided for them.

### Live-data requirement (quote the lecturer verbatim, then map)

> Requirement: "use live data instead of static data." Fulfilment: (1) live
> X API ingestion polling every 30 minutes, classified by the same NLP
> pipeline and surfaced on the Line Status board tagged `source: "x_live"`;
> (2) live in-app crowd reports processed in real time. The historical X
> corpus is used only for model training, as is standard for ML systems.

---

## 🩻 Honest blindspots (current)

1. **Line Status is participatory, not an operator telemetry feed** — no
   Malaysian rail service-alert feed is published. Partially closed: official
   **@AskRapidKL** posts *are* now ingested and weighted authoritative
   (`x_official`, confirms alone), so operator announcements do reach the
   board — but the board's baseline signal remains crowd reports, and even a
   corroborated block expires after 30 minutes. Seed before demos:
   `python scripts/seed_demo_alerts.py` (no `--clear` — it would wipe the real
   x_live rows).
2. ~~Live external ingestion awaiting token~~ — **RESOLVED (11 July 2026)**:
   the X API moved to pay-per-use credits (~US$0.005/post read, no
   subscription to cancel), the token is in `backend/.env`, and the feed has
   been running live since — real Malaysian complaints classified, tagged and
   displayed with source badges. 11 offline ingestion tests.
3. **NLP small classes and live distribution shift** — `safety` (1 sample) is
   merged into `other`, so every trained class has ≥20 samples and macro-F1
   meets the ≥0.65 criterion. Remaining: crowding/staff test sets are only 9
   and 4 samples, so their F1 is noisy; and live X text triggers the Gemini
   gate on **92.2%** of traffic (measured) because live tweets are longer and
   noisier than the training rows. Both are addressed by the live labelling
   pass: every scanned tweet is captured to
   `data/nlp/interim/live_x_labelling.csv` with its prediction; hand-label
   ~50 and run `merge_and_retrain.py --batch` for a before/after fallback rate
   (LIVE_DATA_PLAN.md Part C).
3b. ~~RAG corpus predates LRT3~~ — **RESOLVED (July 2026)**: corpus now contains
   LRT3 line info, the LRT3 fare table, operating hours, and the full
   156-station integrated fare matrix (cash + cashless, validated). Embeddings
   rebuild automatically on next backend start (~1,903 chunks — first start
   after refresh takes longer; keyword fallback covers the gap).
4. **Geocoding needs internet** (Nominatim/Photon) — station-to-station routing
   stays fully offline; tests mock geocoding.
5. **Gemini dependency** — RAG + NLP fallback + augmentation. Defence: local
   model first, LLM only under confidence thresholds; all orchestration,
   routing, retrieval logic is original work.
6. **No frontend e2e tests** — backend suite exists; Playwright is future work.
7. **Interchange walk times are estimates** validated by local knowledge, not
   measured surveys (BU 12 min, Glenmarie 8 min).
8. **Web-only** — mobile-responsive browser app, no native app.
9. **Walk-safety survey is subjective** — 161 stations rated on 5 CPTED factors
   by ONE surveyor from Street View imagery (~2024), not site visits or police
   crime data. Multi-exit stations are rated on their worst exit only, and
   `people_nearby` estimates perceived off-peak activity that a daytime still
   cannot verify. The feature is warning-only and never alters routing; the
   limitation is stated in the loader docstring, both UI toggle descriptions,
   and the user-facing note text.
10. **Voice mishearings are patched by a curated dictionary** — the residual
   errors cluster at 71–77 string similarity, just under the fuzzy cutoff, and
   the gap cannot be closed by loosening it (75 would admit "tadi" → TTDI, and
   "tadi" is everyday Malay). Entries are real observed failures, not guesses,
   but the list does not generalise to a station nobody has spoken yet.
11. **Lost property is absent from the RAG corpus** — verified by searching the
   chunk store, so the refusal is correct rather than a retrieval bug. NOT
   patched with ungrounded generation: the project's claim is answers grounded
   in official documents, and a fluent invented procedure would trade a
   documented limitation for a hallucination risk.

## Likely examiner questions

| Question | Answer |
|---|---|
| Why TF-IDF + LR instead of BERT? | Small labelled corpus (<900 rows), interpretability, millisecond inference; LLM fallback covers uncertain cases. Ablation shows targeted augmentation beat architecture change. |
| What's your contribution vs Gemini? | System design: confidence-gated hybrid pipeline, GTFS graph + schedule-derived Dijkstra + top-K, preference relaxation, augmentation methodology, closed detect→reroute loop. Gemini is a gated component — and the measured 92.2% escalation rate on live traffic (distribution shift) is itself a finding: the gate detected that the local model was out of its depth and escalated, exactly as designed. |
| Why did accuracy dip after augmentation? | Macro-F1 rose 0.50→0.65; minority classes (crowding, staff) went 0%→75% F1. For a participatory system, catching minority complaint types beats overall accuracy. |
| Is the line status real-time? | It processes reports in real time; sources are crowd reports plus the live X API feed. No fake operator-feed claims — the footer says so on every page. |
| Can one person (or one tweet) reroute everyone? | No. Weighted corroboration: a scraped tweet is 0.4, an in-app/voice report 1.0, an official @AskRapidKL post 2.0, and acting needs 2.0 — so one tweet only ever *shows* an amber advisory. Spammed duplicate text counts once. Full table in `TRUST_MODEL.md`. |
| A tweet complaining about last week's breakdown — false alarm? | No: explicit past phrases (EN/BM) and calendar dates older than 2 days suppress the alert flag, unless an ongoing marker ("still", "since", "masih", "lagi") overrides. This was found *from live data* — a dated news recap raised a false alert, which drove the guard. |
| Why do official announcements confirm instantly but crowd reports don't? | Cost asymmetry: showing information early is cheap if wrong, rerouting everyone is expensive if wrong. The operator is authoritative, so it acts alone; anonymous signals must agree first. |
| Where do travel times come from? | Official GTFS `stop_times.txt` — consecutive scheduled arrivals per edge (179 edges); constants only as fallback. |
| What if a user types a typo or a mall name? | Levenshtein auto-correct / did-you-mean; place names geocode to the nearest station with walking guidance. Demo it live. |
| Where are the tests? | `backend/tests` — 190 offline tests; they caught two real routing defects on first run. |
| A single station is reported — does the whole line go red? | Yes for the lines *serving that station*, no for others. A "Masjid Jamek down" report lights KJ+AG+PH (all three platforms are there) and leaves KGL/PYL/MR/BRT/SA untouched. Each affected line card shows a "Reported at: 📍 Masjid Jamek" chip so the location is visible, not just the colour. |
| Do interchange transfers count as sheltered? | Driven by `data/raw/shelter/interchange_shelter.csv`. Currently only Bukit Bintang (KGL↔Monorail) is not-covered; every other surveyed transfer is covered. The feature usually informs (🌧 umbrella warning) rather than reroutes, because most walks turned out to be covered. |

## Pre-demo checklist

1. `python scripts/seed_demo_alerts.py` (fresh timestamps)
2. Backend `uvicorn main:app --port 8000` · frontend `npm run dev`
3. Signed in with Home/Work set (1-click commute card)
4. Rehearse the word-for-word 3-minute script in `DEMO_SCRIPT.md` (typo search →
   place search → simulate disruption → "plan around this" → fare question →
   X-live evidence), including its contingency table

## Key files

| Area | Files |
|---|---|
| Agents | `backend/agents/{nlp_agent,rerouting_agent,rag_agent,transcribe_agent,ingestion_agent,orchestrator}.py` |
| Deterministic bypasses | `backend/agents/{fare_lookup,net_guard}.py` |
| Tests | `backend/tests/` (pytest, offline) |
| IR pipeline | `scripts/{merge_and_retrain,train_with_smote,augment_with_gemini}.py` |
| Demo prep | `scripts/seed_demo_alerts.py`, `scripts/fetch_govdata.py` |
| Live pipeline | `LIVE_DATA_PIPELINE.md`, `backend/agents/ingestion_agent.py` |
| Design system | `DESIGN.md`, `frontend/app/globals.css` |
| UI test list | `FRONTEND_CHECKLIST.md` |
