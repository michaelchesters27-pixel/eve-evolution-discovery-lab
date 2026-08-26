create table if not exists public.live_trader_zone_retrace_learning_state (
  symbol text primary key,
  strategy_key text not null default 'zone_retrace_v1',
  version text not null default 'eve-live-zone-retrace-specialist-v58',
  cycle_count bigint not null default 0,
  last_cycle_at timestamptz,
  rows_evaluated bigint not null default 0,
  relevant_episodes bigint not null default 0,
  execution_evidence jsonb not null default '{}'::jsonb,
  best_execution text,
  promoted_execution text,
  status text not null default 'learning',
  updated_at timestamptz not null default now()
);

comment on table public.live_trader_zone_retrace_learning_state is
  'Real worker evidence for EVE Live Trader zone-retracement specialist. cycle_count increments only when the production worker evaluates historical execution evidence.';
