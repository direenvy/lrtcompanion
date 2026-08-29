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
  mode       text,   -- 'keyword' or 'semantic'
  created_at timestamptz default now()
);

create table if not exists feedback_logs (
  id         bigserial primary key,
  question   text,
  answer     text,
  rating     integer,  -- 1 = thumbs up, -1 = thumbs down
  created_at timestamptz default now()
);
