create table if not exists public.live_trader_historical_learning (
  historical_episode_key text primary key,
  symbol text not null,
  candle_time timestamptz not null,
  observed_at timestamptz not null,
  setup_family text not null,
  independence_key text not null,
  bias text not null default 'neutral',
  confidence integer,
  price double precision not null,
  session text,
  regime text,
  market_state jsonb not null default '{}'::jsonb,
  zones jsonb not null default '{}'::jsonb,
  trade_idea jsonb not null default '{}'::jsonb,
  challenger_results jsonb not null default '{}'::jsonb,
  best_challenger text,
  path_complete boolean not null default false,
  m1_path_bars integer not null default 0,
  endpoint_lag_seconds double precision,
  resolved_price double precision,
  direction_correct boolean,
  trade_outcome text,
  realised_r double precision,
  learning_success boolean,
  evidence_weight double precision not null default 0.25,
  engine_version text not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_live_trader_hist_family
  on public.live_trader_historical_learning(setup_family, observed_at desc);
create index if not exists idx_live_trader_hist_independence
  on public.live_trader_historical_learning(independence_key, observed_at desc);
create index if not exists idx_live_trader_hist_observed
  on public.live_trader_historical_learning(observed_at desc);

alter table public.live_trader_historical_learning enable row level security;
revoke all on public.live_trader_historical_learning from anon, authenticated;
grant all on public.live_trader_historical_learning to service_role;

create table if not exists public.live_trader_historical_state (
  symbol text primary key,
  cursor_time timestamptz,
  historical_rows_scanned bigint not null default 0,
  episodes_recorded bigint not null default 0,
  scored_episodes bigint not null default 0,
  challenger_runs bigint not null default 0,
  last_cycle_at timestamptz,
  last_error text,
  engine_version text not null,
  updated_at timestamptz not null default now()
);

alter table public.live_trader_historical_state enable row level security;
revoke all on public.live_trader_historical_state from anon, authenticated;
grant all on public.live_trader_historical_state to service_role;

-- Preserve but quarantine forward-learning samples produced while IC Markets
-- would be closed, or whose 60-minute horizon crosses the Friday close.
update public.live_trader_opinions
set independent_sample = false,
    market_state = jsonb_set(
      coalesce(market_state, '{}'::jsonb),
      '{learning_observation}',
      coalesce(market_state->'learning_observation', '{}'::jsonb) ||
        jsonb_build_object(
          'market_tradable', false,
          'excluded_reason', 'broker_market_closed_or_horizon_crosses_weekend'
        ),
      true
    )
where learning_version = 'eve-live-learning-family-v1'
  and independent_sample = true
  and (
    extract(dow from observed_at at time zone 'America/New_York') = 6
    or (extract(dow from observed_at at time zone 'America/New_York') = 0
        and (observed_at at time zone 'America/New_York')::time < time '17:00')
    or (extract(dow from observed_at at time zone 'America/New_York') = 5
        and (observed_at at time zone 'America/New_York')::time >= time '16:00')
  );
