-- CDN-Sentinel durable state. Apply with `supabase db push` using a project
-- access token or through the Supabase SQL editor. Server-only secret keys
-- access these tables through the Data API; browser roles receive no grants.

create table if not exists public.cdn_simulation_state (
  state_key text primary key,
  simulation_id text not null,
  payload jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists public.cdn_simulation_history (
  archive_id uuid primary key,
  simulation_id text not null,
  ended_at timestamptz not null,
  payload jsonb not null,
  created_at timestamptz not null default now()
);
create index if not exists cdn_simulation_history_simulation_idx
  on public.cdn_simulation_history (simulation_id, ended_at desc);

create table if not exists public.cdn_watermark_registry (
  key_id text not null,
  marker text not null,
  token text not null,
  created_at double precision not null,
  algorithm_version text not null,
  primary key (key_id, marker)
);
create index if not exists cdn_watermark_registry_token_idx
  on public.cdn_watermark_registry (key_id, token);

create table if not exists public.cdn_forensic_claims (
  watermark_id text primary key,
  key_id text not null,
  marker text not null,
  claim_token text not null,
  claim_json jsonb not null,
  claim_hash text not null,
  created_at double precision not null,
  session_id text,
  content_id text,
  segment_range text,
  algorithm_id text,
  server_id text,
  unique (key_id, marker)
);
create unique index if not exists cdn_forensic_claims_session_node_idx
  on public.cdn_forensic_claims (key_id, session_id, content_id, segment_range, algorithm_id, server_id)
  where session_id is not null;

create table if not exists public.cdn_forensic_events (
  event_id bigint generated always as identity primary key,
  key_id text not null,
  watermark_id text,
  event_type text not null,
  payload_json jsonb not null,
  payload_hash text not null,
  previous_hash text,
  created_at double precision not null
);
create index if not exists cdn_forensic_events_key_idx
  on public.cdn_forensic_events (key_id, event_id);

create table if not exists public.cdn_ab_sessions (
  session_id text primary key,
  client_id text not null,
  content_id text not null,
  watermark_id text not null,
  cache_id text not null,
  fingerprint text not null,
  record_mac text not null,
  created_at double precision not null,
  unique (content_id, fingerprint)
);
create index if not exists cdn_ab_sessions_content_idx
  on public.cdn_ab_sessions (content_id, fingerprint);

alter table public.cdn_simulation_state enable row level security;
alter table public.cdn_simulation_history enable row level security;
alter table public.cdn_watermark_registry enable row level security;
alter table public.cdn_forensic_claims enable row level security;
alter table public.cdn_forensic_events enable row level security;
alter table public.cdn_ab_sessions enable row level security;

revoke all on all tables in schema public from anon, authenticated;
grant select, insert, update, delete on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;
