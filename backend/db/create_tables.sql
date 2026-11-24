-- Run this once in Supabase Dashboard > SQL Editor

create table if not exists disruption_logs (
  id               bigserial primary key,
  text             text,
  sentiment        text,
  issue_type       text,
  disruption_alert boolean,
  created_at       timestamptz default now()
);

create table if not exists chat_logs (
  id         bigserial primary key,
  question   text,
  answer     text,
  mode       text,   -- 'keyword' | 'semantic' | 'semantic_pgvector' | 'fare_lookup'
  -- Verification verdict for this answer: supported | partial | unsupported |
  -- unchecked (the checker could not run) | skipped (no model was involved).
  -- Nullable: rows written before the check existed stay NULL rather than
  -- being backfilled with a guess.
  grounding  text,
  created_at timestamptz default now()
);

-- Existing deployments: add the column without touching the rows already there.
alter table chat_logs add column if not exists grounding text;

create table if not exists feedback_logs (
  id         bigserial primary key,
  question   text,
  answer     text,
  rating     integer,  -- 1 = thumbs up, -1 = thumbs down
  created_at timestamptz default now()
);

-- Live-ingestion cursor. One row, id = 1.
--
-- This lived in backend/models/x_ingest_state.json, on the container's own
-- disk. That worked while the instance was always-on, and breaks on a tier
-- where the instance sleeps: the file goes with the container, so every wake
-- starts with no cursor and no seen-id list, re-fetches the same tweets,
-- re-classifies them, and writes duplicate rows. A redeploy did the same thing
-- on any tier. Durable storage is the fix, and Supabase is already a hard
-- dependency, so it costs no new infrastructure.
--
-- seen_ids is capped by the application (MAX_SEEN_IDS), not here.
create table if not exists ingest_state (
  id             integer primary key default 1,
  newest_id      text,          -- X since_id cursor
  seen_ids       jsonb default '[]'::jsonb,
  last_poll      timestamptz,
  last_result    text,
  tweets_scanned integer default 0,
  alerts_raised  integer default 0,
  alerts_gated   integer default 0,
  updated_at     timestamptz default now(),
  constraint ingest_state_single_row check (id = 1)
);

-- No client should ever read or write the ingestion cursor: it is touched only
-- by the backend, which uses the service key and bypasses RLS. The anon key is
-- public — it ships inside the browser bundle — so without this, anyone could
-- set newest_id far into the future (every later poll then skips real tweets)
-- or clear seen_ids (every poll re-processes the same posts and burns the
-- monthly X quota). The cursor is a control surface, not just data.
--
-- Enabled with NO policies on purpose. That denies anon and authenticated
-- everything, which is the intended access level here.
alter table ingest_state enable row level security;
