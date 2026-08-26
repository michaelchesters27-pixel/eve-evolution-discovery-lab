-- Zone Retracement Specialist v68 exact live-entry replay ledger.
-- Mirrors production migration 20260826165746.

create table if not exists public.live_trader_zone_retrace_live_policy_replays (
    replay_key text primary key,
    historical_episode_key text not null,
    independence_key text not null,
    symbol text not null,
    observed_at timestamptz not null,
    entry_at timestamptz,
    status text not null,
    side text,
    entry double precision,
    stop double precision,
    target double precision,
    target_r double precision,
    source_zone jsonb,
    clear_bias_gate jsonb,
    confirmation jsonb,
    path_complete boolean not null default false,
    trade_outcome text,
    realised_r double precision,
    learning_success boolean,
    replay_version text not null,
    evaluation_horizon_minutes integer not null,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists uq_live_trader_zone_retrace_live_policy_independence
    on public.live_trader_zone_retrace_live_policy_replays(symbol, independence_key, replay_version);
create index if not exists ix_live_trader_zone_retrace_live_policy_observed
    on public.live_trader_zone_retrace_live_policy_replays(symbol, observed_at);
create index if not exists ix_live_trader_zone_retrace_live_policy_status
    on public.live_trader_zone_retrace_live_policy_replays(symbol, replay_version, status);

create table if not exists public.live_trader_zone_retrace_live_policy_state (
    symbol text primary key,
    replay_version text not null,
    status text not null default 'running',
    eligible_episodes integer not null default 0,
    processed_episodes integer not null default 0,
    triggered integer not null default 0,
    wins integer not null default 0,
    losses integer not null default 0,
    breakeven integer not null default 0,
    total_r double precision not null default 0,
    expectancy_per_opportunity_r double precision,
    expectancy_per_triggered_r double precision,
    trigger_rate double precision,
    promoted boolean not null default false,
    completed boolean not null default false,
    last_processed_at timestamptz,
    last_error text,
    policy jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

comment on table public.live_trader_zone_retrace_live_policy_replays is
'Independent causal replays of the actual Zone Retracement Specialist entry geometry. Kept separate from legacy 2.2R immediate-market challenger evidence.';
comment on table public.live_trader_zone_retrace_live_policy_state is
'Aggregate progress and expectancy for the exact live zone-retrace confirmation entry replay.';
