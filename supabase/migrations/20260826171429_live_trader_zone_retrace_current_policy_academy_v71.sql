-- Current-policy Zone Retracement Academy ledger.
-- Mirrors production migration 20260826171429.

create table if not exists public.live_trader_zone_retrace_current_policy_opportunities (
    opportunity_key text primary key,
    independence_key text not null,
    symbol text not null,
    observed_at timestamptz not null,
    session text,
    bias text,
    start_price double precision,
    atr double precision,
    source_zone jsonb,
    clear_bias_gate jsonb,
    entry_at timestamptz,
    side text,
    entry double precision,
    stop double precision,
    target double precision,
    target_r double precision,
    confirmation jsonb,
    status text not null,
    path_complete boolean not null default false,
    trade_outcome text,
    realised_r double precision,
    learning_success boolean,
    academy_version text not null,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index if not exists uq_live_trader_zone_retrace_current_policy_independence
    on public.live_trader_zone_retrace_current_policy_opportunities(symbol, independence_key, academy_version);
create index if not exists ix_live_trader_zone_retrace_current_policy_observed
    on public.live_trader_zone_retrace_current_policy_opportunities(symbol, observed_at);
create index if not exists ix_live_trader_zone_retrace_current_policy_status
    on public.live_trader_zone_retrace_current_policy_opportunities(symbol, academy_version, status);

create table if not exists public.live_trader_zone_retrace_current_policy_state (
    symbol text primary key,
    academy_version text not null,
    status text not null default 'scanning',
    cursor_time timestamptz,
    m1_coverage_start timestamptz,
    rows_scanned bigint not null default 0,
    opportunities_found integer not null default 0,
    scorable_opportunities integer not null default 0,
    unscorable_opportunities integer not null default 0,
    triggered integer not null default 0,
    wins integer not null default 0,
    losses integer not null default 0,
    breakeven integer not null default 0,
    total_r double precision not null default 0,
    expectancy_per_opportunity_r double precision,
    expectancy_per_triggered_r double precision,
    trigger_rate double precision,
    caught_up boolean not null default false,
    promoted boolean not null default false,
    last_cycle_at timestamptz,
    last_error text,
    policy jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

comment on table public.live_trader_zone_retrace_current_policy_opportunities is
'Causal opportunities discovered under the current live structural-bias, London-session, ranked-zone and zone-confirmation policy.';
comment on table public.live_trader_zone_retrace_current_policy_state is
'Archive scan progress and exact live-policy expectancy for the current Zone Retracement Specialist contract.';
