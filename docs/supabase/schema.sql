-- Supabase schema for the Kalshi Trading Radar.
-- Run this once in Supabase SQL Editor.
-- The monitor writes with SUPABASE_SERVICE_ROLE_KEY.
-- The public read policies let Streamlit read public market data with an anon key.

create table if not exists public.market_state (
  ticker text primary key,
  updated_at timestamptz not null,
  series_ticker text not null,
  title text not null,
  action text not null,
  fair_probability numeric,
  yes_bid numeric,
  yes_ask numeric,
  no_bid numeric,
  no_ask numeric,
  spread numeric,
  expected_value numeric,
  expected_roi numeric,
  fee_estimate numeric,
  volume_24h numeric,
  open_interest numeric,
  risk_flags text not null default '',
  reason text not null default '',
  market_url text not null default ''
);

create index if not exists market_state_action_idx on public.market_state (action);
create index if not exists market_state_updated_at_idx on public.market_state (updated_at desc);
create index if not exists market_state_series_idx on public.market_state (series_ticker);

create table if not exists public.market_observations (
  id bigint generated always as identity primary key,
  observed_at timestamptz not null,
  ticker text not null,
  series_ticker text not null,
  title text not null,
  action text not null,
  fair_probability numeric,
  yes_bid numeric,
  yes_ask numeric,
  no_bid numeric,
  no_ask numeric,
  spread numeric,
  expected_value numeric,
  expected_roi numeric,
  fee_estimate numeric,
  volume_24h numeric,
  open_interest numeric,
  risk_flags text not null default '',
  reason text not null default '',
  market_url text not null default ''
);

create index if not exists market_observations_observed_at_idx on public.market_observations (observed_at desc);
create index if not exists market_observations_ticker_observed_idx on public.market_observations (ticker, observed_at desc);

create table if not exists public.signal_events (
  id bigint generated always as identity primary key,
  observed_at timestamptz not null,
  ticker text not null,
  series_ticker text not null,
  title text not null,
  action text not null,
  expected_value numeric,
  expected_roi numeric,
  price numeric,
  risk_flags text not null default '',
  reason text not null default '',
  market_url text not null default '',
  payload jsonb not null default '{}'::jsonb
);

create index if not exists signal_events_observed_at_idx on public.signal_events (observed_at desc);
create index if not exists signal_events_action_idx on public.signal_events (action);

create table if not exists public.kalshi_monitor_runs (
  id bigint generated always as identity primary key,
  observed_at timestamptz not null,
  status text not null,
  message text not null,
  markets_scanned integer not null default 0,
  signals_saved integer not null default 0,
  actionable_count integer not null default 0,
  memory_mb numeric,
  metadata jsonb not null default '{}'::jsonb
);

create index if not exists kalshi_monitor_runs_observed_at_idx on public.kalshi_monitor_runs (observed_at desc);
create index if not exists kalshi_monitor_runs_status_idx on public.kalshi_monitor_runs (status);

create table if not exists public.system_heartbeat (
  component text primary key,
  updated_at timestamptz not null,
  status text not null,
  message text not null,
  metadata jsonb not null default '{}'::jsonb
);

alter table public.market_state enable row level security;
alter table public.market_observations enable row level security;
alter table public.signal_events enable row level security;
alter table public.kalshi_monitor_runs enable row level security;
alter table public.system_heartbeat enable row level security;

drop policy if exists "public read market_state" on public.market_state;
create policy "public read market_state"
on public.market_state for select
using (true);

drop policy if exists "public read market_observations" on public.market_observations;
create policy "public read market_observations"
on public.market_observations for select
using (true);

drop policy if exists "public read signal_events" on public.signal_events;
create policy "public read signal_events"
on public.signal_events for select
using (true);

drop policy if exists "public read kalshi_monitor_runs" on public.kalshi_monitor_runs;
create policy "public read kalshi_monitor_runs"
on public.kalshi_monitor_runs for select
using (true);

drop policy if exists "public read system_heartbeat" on public.system_heartbeat;
create policy "public read system_heartbeat"
on public.system_heartbeat for select
using (true);

grant usage on schema public to anon, authenticated;
grant select on public.market_state to anon, authenticated;
grant select on public.market_observations to anon, authenticated;
grant select on public.signal_events to anon, authenticated;
grant select on public.kalshi_monitor_runs to anon, authenticated;
grant select on public.system_heartbeat to anon, authenticated;
