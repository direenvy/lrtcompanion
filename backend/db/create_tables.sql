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
